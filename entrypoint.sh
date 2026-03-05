#!/usr/bin/env bash
# EigenClaw entrypoint — runs inside container at startup.
#
# What this does:
#   1. Validates CHUTES_API_KEY is present
#   2. Seeds OpenClaw config if first boot (openclaw onboard)
#   3. Authenticates Chutes using env var (no TTY needed)
#   4. Merges ALL config atomically via Python (single JSON write)
#   5. Starts OpenClaw gateway on 0.0.0.0:18789
#
# PERF FIX: Previous version called `openclaw config set` 15+ times. Each call
# triggers a Doctor diagnostic taking ~60s. Total boot: 20+ min.
# Now we merge all config in a single Python JSON write: ~2s total.

set -exuo pipefail

export CI=1

CHUTES_BASE_URL="https://llm.chutes.ai/v1"
CHUTES_DEFAULT_MODEL_REF="chutes/zai-org/GLM-4.7-TEE"
CHUTES_FAST_MODEL_REF="chutes/zai-org/GLM-4.7-Flash"
DEFEYES_BASE_URL="https://defeyes-api.vercel.app"
GATEWAY_PORT=18789

log() { echo "[eigenclaw] $*"; }

# ── 0. Debug ─────────────────────────────────────────────────────────────────
log "Env check: DOMAIN=${DOMAIN:-<unset>} APP_PORT=${APP_PORT:-<unset>} ACME_STAGING=${ACME_STAGING:-<unset>}"
log "User: $(whoami) uid=$(id -u) | Caddy: $(test -x /usr/local/bin/caddy && getcap /usr/local/bin/caddy 2>/dev/null || echo 'N/A')"

# ── 1. Validate ──────────────────────────────────────────────────────────────
if [ -z "${CHUTES_API_KEY:-}" ]; then
  log "ERROR: CHUTES_API_KEY is not set."
  log "Pass it at deploy time: ecloud compute app deploy --env CHUTES_API_KEY=xxx"
  exit 1
fi
log "CHUTES_API_KEY present — starting setup..."

if [ -z "${OPENCLAW_TOKEN:-}" ]; then
  log "ERROR: OPENCLAW_TOKEN is required for Fly.io (OpenClaw refuses 0.0.0.0 without auth)."
  log "Set it: fly secrets set OPENCLAW_TOKEN=your_token"
  exit 1
fi
export OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_TOKEN"

# ── 2. Seed OpenClaw config if first boot ────────────────────────────────────
if [ "${OPENCLAW_ENABLE_FIRECRAWL_CONFIG:-false}" != "true" ] && [ -f "$HOME/.openclaw/openclaw.json" ]; then
  if python3 - "$HOME/.openclaw/openclaw.json" <<'PY'
import pathlib, sys
cfg = pathlib.Path(sys.argv[1])
text = cfg.read_text(errors="ignore")
sys.exit(0 if '"firecrawl"' in text else 1)
PY
  then
    log "Detected incompatible firecrawl config keys; resetting OpenClaw config."
    rm -f "$HOME/.openclaw/openclaw.json"
  fi
fi

if [ ! -f "$HOME/.openclaw/openclaw.json" ]; then
  log "First boot — seeding OpenClaw config..."
  openclaw onboard --non-interactive --accept-risk --auth-choice skip 2>&1 || true
  log "Config seeded (gateway.mode set in atomic merge below)."
fi

# ── 3. Authenticate Chutes (non-interactive) ─────────────────────────────────
log "Authenticating with Chutes..."
CHUTES_TOKEN_DIR="$HOME/.openclaw/auth"
mkdir -p "$CHUTES_TOKEN_DIR"
echo "$CHUTES_API_KEY" > "$CHUTES_TOKEN_DIR/chutes.token" 2>/dev/null || true
timeout 10s bash -c "printf '%s\n' '$CHUTES_API_KEY' | openclaw models auth paste-token --provider chutes 2>&1" </dev/null || true
log "Chutes auth step complete (best-effort)."

# ── 4. Build model list ──────────────────────────────────────────────────────
log "Fetching Chutes model catalog..."
MODELS_JSON=""
if [ "${OPENCLAW_FETCH_MODEL_CATALOG:-false}" = "true" ] && MODELS_FETCHED_JSON=$(node -e '
async function run() {
  try {
    const res = await fetch("https://llm.chutes.ai/v1/models");
    if (!res.ok) throw new Error("API error: " + res.statusText);
    const data = await res.json();
    const mapped = data.data.map(m => ({
      id: m.id,
      name: m.id,
      reasoning: m.supported_features?.includes("reasoning") || false,
      input: (m.input_modalities || ["text"]).filter(i => i === "text" || i === "image"),
      cost: {
        input: m.pricing?.prompt || 0,
        output: m.pricing?.completion || 0,
        cacheRead: 0,
        cacheWrite: 0
      },
      contextWindow: m.context_length || 128000,
      maxTokens: m.max_output_length || 4096
    }));
    console.log(JSON.stringify(mapped));
  } catch (e) {
    process.stderr.write(e.message + "\n");
    process.exit(1);
  }
}
run();' 2>/tmp/chutes-models.err); then
  MODELS_JSON="$MODELS_FETCHED_JSON"
else
  if [ "${OPENCLAW_FETCH_MODEL_CATALOG:-false}" = "true" ]; then
    log "Model catalog fetch failed; will use fallback defaults."
    if [ -s /tmp/chutes-models.err ]; then
      log "Catalog error: $(tr '\n' ' ' < /tmp/chutes-models.err | cut -c1-220)"
    fi
  else
    log "Skipping full model-catalog fetch (OPENCLAW_FETCH_MODEL_CATALOG is not true)."
  fi
fi

if [ -n "$MODELS_JSON" ]; then
  if ! node -e '
try {
  const parsed = JSON.parse(process.argv[1]);
  if (!Array.isArray(parsed)) process.exit(2);
} catch {
  process.exit(1);
}
' "$MODELS_JSON" >/dev/null 2>&1; then
    log "Fetched model catalog is invalid JSON; using fallback defaults."
    MODELS_JSON=""
  fi
fi

if [ -z "$MODELS_JSON" ]; then
  log "Could not fetch model catalog — using defaults."
  MODELS_JSON='[
    {"id":"zai-org/GLM-4.7-TEE","name":"GLM 4.7 TEE","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096},
    {"id":"zai-org/GLM-4.7-Flash","name":"GLM 4.7 Flash","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096},
    {"id":"deepseek-ai/DeepSeek-V3.2-TEE","name":"DeepSeek V3.2 TEE","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096}
  ]'
fi

# ── 5. Atomic config merge (replaces 15+ individual openclaw config set) ─────
log "Merging all config atomically via Python..."

ORIGINS_JSON="[]"
if [ -n "${CONTROL_UI_ALLOWED_ORIGINS_JSON:-}" ]; then
  ORIGINS_JSON="${CONTROL_UI_ALLOWED_ORIGINS_JSON}"
elif [ -n "${DOMAIN:-}" ]; then
  ORIGINS_JSON="[\"https://${DOMAIN}\",\"https://${DOMAIN}:443\",\"http://${DOMAIN}\",\"http://${DOMAIN}:80\",\"https://www.${DOMAIN}\",\"https://www.${DOMAIN}:443\",\"http://www.${DOMAIN}\",\"http://www.${DOMAIN}:80\"]"
fi

python3 - "$HOME/.openclaw/openclaw.json" \
  "$CHUTES_BASE_URL" \
  "$CHUTES_DEFAULT_MODEL_REF" \
  "$CHUTES_FAST_MODEL_REF" \
  "$OPENCLAW_TOKEN" \
  "$ORIGINS_JSON" \
  "${TELEGRAM_BOT_TOKEN:-}" \
  "${FIRECRAWL_BASE_URL:-}" \
  "${FIRECRAWL_API_KEY:-}" \
  "${OPENCLAW_ENABLE_FIRECRAWL_CONFIG:-false}" \
  "$MODELS_JSON" \
  <<'PYMERGE'
import json, sys, pathlib

cfg_path   = pathlib.Path(sys.argv[1])
base_url   = sys.argv[2]
default_model = sys.argv[3]
fast_model = sys.argv[4]
token      = sys.argv[5]
origins    = json.loads(sys.argv[6])
tg_token   = sys.argv[7]
fc_url     = sys.argv[8]
fc_key     = sys.argv[9]
fc_enabled = sys.argv[10] == "true"
models     = json.loads(sys.argv[11])

cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}

def deep_set(d, path, val):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = val

deep_set(cfg, "models.providers.chutes", {
    "baseUrl": base_url,
    "api": "openai-completions",
    "auth": "api-key",
    "models": models
})

model_entries = {}
for m in models:
    model_entries["chutes/" + m["id"]] = {}
model_entries["chutes-fast"]   = {"alias": fast_model}
model_entries["chutes-pro"]    = {"alias": "chutes/deepseek-ai/DeepSeek-V3.2-TEE"}
model_entries["chutes-vision"] = {"alias": "chutes/chutesai/Mistral-Small-3.2-24B-Instruct-2506"}

deep_set(cfg, "agents.defaults", {
    "model": {
        "primary": default_model,
        "fallbacks": ["chutes/deepseek-ai/DeepSeek-V3.2-TEE", "chutes/zai-org/GLM-4.7-Flash"]
    },
    "imageModel": {
        "primary": "chutes/chutesai/Mistral-Small-3.2-24B-Instruct-2506",
        "fallbacks": ["chutes/zai-org/GLM-4.7-Flash"]
    },
    "models": model_entries,
    "tools": {
        "allow": ["exec", "read", "web_fetch", "sessions_list", "sessions_history", "sessions_send"],
        "deny": ["browser", "canvas", "discord", "write", "edit"]
    }
})

deep_set(cfg, "auth.profiles.chutes:manual", {"provider": "chutes", "mode": "api_key"})

deep_set(cfg, "gateway.auth.token", token)
deep_set(cfg, "gateway.controlUi.allowInsecureAuth", True)
deep_set(cfg, "gateway.controlUi.dangerouslyDisableDeviceAuth", True)
if origins:
    deep_set(cfg, "gateway.controlUi.allowedOrigins", origins)
deep_set(cfg, "gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback", True)
deep_set(cfg, "gateway.trustedProxies", ["127.0.0.1/8","10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"])
deep_set(cfg, "gateway.mode", "local")
# Use custom + 0.0.0.0 for Fly.io (lan may not bind correctly in container)
deep_set(cfg, "gateway.bind", "custom")
deep_set(cfg, "gateway.customBindHost", "0.0.0.0")
deep_set(cfg, "update.checkOnStart", False)
deep_set(cfg, "update.auto.enabled", False)

if tg_token:
    deep_set(cfg, "channels.telegram.enabled", True)
    deep_set(cfg, "channels.telegram.botToken", tg_token)
    deep_set(cfg, "channels.telegram.dmPolicy", "pairing")
    deep_set(cfg, "channels.telegram.groupPolicy", "allowlist")

if fc_enabled and fc_url:
    deep_set(cfg, "tools.web.fetch.firecrawl.enabled", True)
    deep_set(cfg, "tools.web.fetch.firecrawl.baseUrl", fc_url)
    deep_set(cfg, "tools.web.fetch.firecrawl.apiKey", fc_key)
    deep_set(cfg, "tools.web.fetch.firecrawl.onlyMainContent", True)
    deep_set(cfg, "tools.web.fetch.firecrawl.maxAgeMs", 86400000)
    deep_set(cfg, "tools.web.fetch.firecrawl.timeoutSeconds", 60)

cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
print("Config merged successfully.", file=sys.stderr)
PYMERGE

log "Config merged. Primary model: $CHUTES_DEFAULT_MODEL_REF (TEE)"
log "Gateway token: ${OPENCLAW_TOKEN:0:6}..."
[ -n "${TELEGRAM_BOT_TOKEN:-}" ] && log "Telegram configured." || log "Telegram not configured."
[ "${OPENCLAW_ENABLE_FIRECRAWL_CONFIG:-false}" = "true" ] && [ -n "${FIRECRAWL_BASE_URL:-}" ] && log "Firecrawl: $FIRECRAWL_BASE_URL" || log "Firecrawl: off"

# ── 6. Export DeFEyes API ─────────────────────────────────────────────────────
export DEFEYES_BASE_URL
[ -n "${DEFEYES_API_KEY:-}" ] && log "DeFEyes: $DEFEYES_BASE_URL" || log "WARNING: DEFEYES_API_KEY not set."

# ── 7. Memory + Audit Pulse ──────────────────────────────────────────────────
WORKSPACE_DIR="$HOME/.openclaw/workspace"
MEMORY_DIR="$WORKSPACE_DIR/memory"
AUDIT_LOG_PATH="$WORKSPACE_DIR/AUDIT_LOG.md"

mkdir -p "$MEMORY_DIR"
touch "$AUDIT_LOG_PATH" || true

rollup_memory() {
  local rollup="$MEMORY_DIR/_ROLLUP.md"
  : > "$rollup" || true
  shopt -s nullglob
  local files=("$MEMORY_DIR"/*.md)
  shopt -u nullglob
  for f in "${files[@]}"; do
    [ "$(basename "$f")" = "_ROLLUP.md" ] && continue
    { echo ""; echo "---"; echo "# $(basename "$f")"; echo ""; cat "$f"; echo ""; } >> "$rollup" || true
  done
}

start_audit_pulse() {
  local enabled="${ENABLE_AUDIT_PULSE:-true}"
  local interval="${AUDIT_PULSE_SECONDS:-14400}"
  [ "$enabled" != "true" ] && { log "Audit pulse disabled."; return 0; }
  [ ! -f "/app/agent/scripts/headless_audit.py" ] && { log "WARNING: headless audit script missing."; return 0; }
  log "Starting headless audit pulse (every ${interval}s)..."
  (
    while true; do
      python3 /app/agent/scripts/headless_audit.py --once 2>&1 || true
      rollup_memory 2>&1 || true
      sleep "$interval" || true
    done
  ) &
}

rollup_memory || true
python3 /app/agent/scripts/headless_audit.py --once 2>&1 || true
start_audit_pulse || true

# ── 8. Start OpenClaw gateway (supervised) ────────────────────────────────────
gateway_pid=""
gateway_started_at="0"
GATEWAY_START_GRACE_SECONDS="${GATEWAY_START_GRACE_SECONDS:-180}"
GATEWAY_RESTART_BACKOFF_SECONDS="${GATEWAY_RESTART_BACKOFF_SECONDS:-5}"
start_gateway() {
  log "Starting OpenClaw gateway on 0.0.0.0:$GATEWAY_PORT (bind=custom)..."
  gateway_started_at="$(date +%s)"
  openclaw gateway run --bind custom --port "$GATEWAY_PORT" 2>&1 &
  gateway_pid="$!"
  log "Gateway process started pid=$gateway_pid"
}

gateway_ok() {
  curl -fsS "http://127.0.0.1:${GATEWAY_PORT}/" >/dev/null 2>&1
}

start_gateway

# Disable trace to avoid flooding logs (watchdog runs every 2–10s)
set +x
while true; do
  now="$(date +%s)"
  age="$(( now - gateway_started_at ))"

  if [ "$age" -lt "$GATEWAY_START_GRACE_SECONDS" ]; then
    sleep 2
    continue
  fi

  if gateway_ok; then
    sleep 10
    continue
  fi

  set -x
  log "Gateway health check failed; restarting..."
  if [ -n "${gateway_pid:-}" ]; then
    kill "$gateway_pid" >/dev/null 2>&1 || true
    sleep 1
    kill -9 "$gateway_pid" >/dev/null 2>&1 || true
  fi
  start_gateway
  set +x
  sleep "$GATEWAY_RESTART_BACKOFF_SECONDS"
done

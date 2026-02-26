#!/usr/bin/env bash
# EigenClaw entrypoint — runs inside EigenCompute TEE at container startup.
#
# What this does (adapted from ParaClaw init.sh for non-interactive TEE use):
#   1. Validates CHUTES_API_KEY is present
#   2. Seeds OpenClaw config if first boot
#   3. Authenticates Chutes using env var (no TTY needed)
#   4. Fetches live model list from Chutes API + applies config atomically
#   5. Starts OpenClaw gateway on 0.0.0.0:18789 (TEE requires 0.0.0.0)
#
# Required env (injected by EigenCompute at deploy time):
#   CHUTES_API_KEY   — from chutes.ai dashboard

set -exuo pipefail

CHUTES_BASE_URL="https://llm.chutes.ai/v1"
CHUTES_DEFAULT_MODEL_REF="chutes/zai-org/GLM-4.7-TEE"   # TEE model — end-to-end verifiable
CHUTES_FAST_MODEL_REF="chutes/zai-org/GLM-4.7-Flash"
DEFEYES_BASE_URL="https://defeyes-api.vercel.app"
GATEWAY_PORT=18789

log() { echo "[eigenclaw] $*"; }

# ── 0. Debug: TLS/networking env + permissions (non-sensitive) ───────────────
log "Env check: DOMAIN=${DOMAIN:-<unset>} APP_PORT=${APP_PORT:-<unset>} ACME_STAGING=${ACME_STAGING:-<unset>}"
log "User: $(whoami) uid=$(id -u) | Caddy: $(test -x /usr/local/bin/caddy && getcap /usr/local/bin/caddy 2>/dev/null || echo 'N/A')"

# ── 1. Validate ───────────────────────────────────────────────────────────────
if [ -z "${CHUTES_API_KEY:-}" ]; then
  log "ERROR: CHUTES_API_KEY is not set."
  log "Pass it at deploy time: ecloud compute app deploy --env CHUTES_API_KEY=xxx"
  exit 1
fi
log "CHUTES_API_KEY present — starting setup..."

# ── 2. Seed OpenClaw config if first boot ────────────────────────────────────
if [ ! -f "$HOME/.openclaw/openclaw.json" ]; then
  log "First boot — seeding OpenClaw config..."
  openclaw onboard --non-interactive --accept-risk --auth-choice skip 2>&1 || true
  openclaw config set gateway.mode local 2>&1
  log "Config seeded."
fi

# ── 3. Authenticate Chutes (non-interactive, via env var) ────────────────────
log "Authenticating with Chutes..."
echo "$CHUTES_API_KEY" | openclaw models auth paste-token --provider chutes 2>&1
log "Chutes auth applied."

# ── 4. Fetch live model list + apply config atomically ───────────────────────
log "Fetching Chutes model catalog..."
MODELS_JSON=$(node -e '
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
run();' 2>&1 || echo "")

# Fallback to known models if API unreachable
if [ -z "$MODELS_JSON" ]; then
  log "Could not fetch model catalog — using defaults."
  MODELS_JSON='[
    {"id":"zai-org/GLM-4.7-TEE","name":"GLM 4.7 TEE","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096},
    {"id":"zai-org/GLM-4.7-Flash","name":"GLM 4.7 Flash","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096},
    {"id":"deepseek-ai/DeepSeek-V3.2-TEE","name":"DeepSeek V3.2 TEE","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096}
  ]'
fi

log "Applying provider + agent config..."

PROVIDER_CONFIG=$(node -e "
const config = {
  baseUrl: '$CHUTES_BASE_URL',
  api: 'openai-completions',
  auth: 'api-key',
  models: $MODELS_JSON
};
console.log(JSON.stringify(config));
")
openclaw config set models.providers.chutes --json "$PROVIDER_CONFIG" 2>&1

AGENT_DEFAULTS=$(node -e "
const modelsJson = $MODELS_JSON;
const modelEntries = {};
modelsJson.forEach(m => { modelEntries['chutes/' + m.id] = {}; });
modelEntries['chutes-fast']   = { alias: '$CHUTES_FAST_MODEL_REF' };
modelEntries['chutes-pro']    = { alias: 'chutes/deepseek-ai/DeepSeek-V3.2-TEE' };
modelEntries['chutes-vision'] = { alias: 'chutes/chutesai/Mistral-Small-3.2-24B-Instruct-2506' };

const config = {
  model: {
    primary: '$CHUTES_DEFAULT_MODEL_REF',
    fallbacks: ['chutes/deepseek-ai/DeepSeek-V3.2-TEE', 'chutes/zai-org/GLM-4.7-Flash']
  },
  imageModel: {
    primary: 'chutes/chutesai/Mistral-Small-3.2-24B-Instruct-2506',
    fallbacks: ['chutes/zai-org/GLM-4.7-Flash']
  },
  models: modelEntries
};
console.log(JSON.stringify(config));
")
openclaw config set agents.defaults --json "$AGENT_DEFAULTS" 2>&1
openclaw config set auth.profiles.\"chutes:manual\" --json '{"provider":"chutes","mode":"api_key"}' 2>&1

log "Config applied. Primary model: $CHUTES_DEFAULT_MODEL_REF (TEE)"

# ── 5. Set gateway token for dashboard auth ──────────────────────────────────
if [ -n "${OPENCLAW_TOKEN:-}" ]; then
  export OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_TOKEN"
  openclaw config set gateway.auth.token "$OPENCLAW_TOKEN" 2>&1 || true
  log "Gateway token set from env: ${OPENCLAW_TOKEN:0:6}..."
else
  log "WARNING: OPENCLAW_TOKEN not set — dashboard will reject connections."
fi

# ── 6. Bypass device-pairing requirement (no exec into TEE) ──────────────────
openclaw config set gateway.controlUi.allowInsecureAuth true 2>&1 || true
openclaw config set gateway.controlUi.dangerouslyDisableDeviceAuth true 2>&1 || true
# Newer OpenClaw builds require explicit Control UI origins for non-loopback access.
# In EigenCompute we sit behind an ingress proxy, so allow Host-header fallback and
# also set explicit origins if DOMAIN is provided.
if [ -n "${DOMAIN:-}" ]; then
  openclaw config set gateway.controlUi.allowedOrigins --json "[\"https://${DOMAIN}\",\"https://www.${DOMAIN}\"]" 2>&1 || true
fi
openclaw config set gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback true 2>&1 || true
openclaw config set gateway.auth.pairingRequired false 2>&1 || true
openclaw config set gateway.trustedProxies '["127.0.0.1/8","10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]' 2>&1 || true
log "Pairing requirement bypassed; trusted proxies set."

# ── 7. Export DeFEyes API for skills/tools ────────────────────────────────────
export DEFEYES_BASE_URL
if [ -n "${DEFEYES_API_KEY:-}" ]; then
  log "DeFEyes API configured: $DEFEYES_BASE_URL (key: ${DEFEYES_API_KEY:0:8}...)"
else
  log "WARNING: DEFEYES_API_KEY not set — DeFi enrichment unavailable."
fi

# ── 8. Continuous Memory + Automation Pulse ───────────────────────────────────
WORKSPACE_DIR="$HOME/.openclaw/workspace"
MEMORY_DIR="$WORKSPACE_DIR/memory"
AUDIT_LOG_PATH="$WORKSPACE_DIR/AUDIT_LOG.md"

mkdir -p "$MEMORY_DIR"
touch "$AUDIT_LOG_PATH" || true

# Consolidate historical memory into a single file for deterministic boot context.
# This approximates “cat memory/*.md into the system prompt” by creating a rollup
# file that the agent reads during Session Startup.
rollup_memory() {
  local rollup="$MEMORY_DIR/_ROLLUP.md"
  : > "$rollup" || true

  shopt -s nullglob
  local files=("$MEMORY_DIR"/*.md)
  shopt -u nullglob

  for f in "${files[@]}"; do
    if [ "$(basename "$f")" = "_ROLLUP.md" ]; then
      continue
    fi
    {
      echo ""
      echo "---"
      echo "# $(basename "$f")"
      echo ""
      cat "$f"
      echo ""
    } >> "$rollup" || true
  done
}

start_audit_pulse() {
  local enabled="${ENABLE_AUDIT_PULSE:-true}"
  local interval="${AUDIT_PULSE_SECONDS:-14400}" # 4 hours

  if [ "$enabled" != "true" ]; then
    log "Audit pulse disabled (ENABLE_AUDIT_PULSE=$enabled)."
    return 0
  fi

  if [ ! -f "/app/agent/scripts/headless_audit.py" ]; then
    log "WARNING: headless audit script missing — pulse not started."
    return 0
  fi

  log "Starting headless audit pulse (every ${interval}s)..."
  (
    while true; do
      log "Audit pulse: running headless audit now..."
      python3 /app/agent/scripts/headless_audit.py --once 2>&1 || true
      rollup_memory 2>&1 || true
      log "Audit pulse: sleeping for ${interval}s..."
      sleep "$interval" || true
    done
  ) &
}

rollup_memory || true
# Run a single audit once at boot so we can confirm persistence quickly
python3 /app/agent/scripts/headless_audit.py --once 2>&1 || true
start_audit_pulse || true

# ── 9. Start OpenClaw gateway (supervised) ────────────────────────────────────
# IMPORTANT: The Control UI has an "Update & Restart" action (RPC: update.run)
# that can trigger a full-process restart where the gateway exits and spawns a
# replacement process. If the gateway is PID 1 (via exec), the container exits
# and your domain goes dark.
#
# So: run a tiny watchdog that keeps the container alive and ensures the gateway
# is responding on localhost. This makes restarts/updates non-fatal.

# Best-effort: disable update hints/auto-updater (safe if keys unsupported)
openclaw config set update.checkOnStart false 2>&1 || true
openclaw config set update.auto.enabled false 2>&1 || true

gateway_pid=""
gateway_started_at="0"
GATEWAY_START_GRACE_SECONDS="${GATEWAY_START_GRACE_SECONDS:-45}"
GATEWAY_RESTART_BACKOFF_SECONDS="${GATEWAY_RESTART_BACKOFF_SECONDS:-5}"
start_gateway() {
  log "Starting OpenClaw gateway on lan:$GATEWAY_PORT..."
  gateway_started_at="$(date +%s)"
  # Let gateway logs flow to platform logs for visibility.
  openclaw gateway run --bind lan --port "$GATEWAY_PORT" 2>&1 &
  gateway_pid="$!"
  log "Gateway process started pid=$gateway_pid"
}

gateway_ok() {
  # Canvas mount is consistently present when gateway is up.
  curl -fsS "http://127.0.0.1:${GATEWAY_PORT}/__openclaw__/canvas/" >/dev/null 2>&1
}

start_gateway

while true; do
  now="$(date +%s)"
  age="$(( now - gateway_started_at ))"

  # Give the gateway time to boot before health enforcement.
  if [ "$age" -lt "$GATEWAY_START_GRACE_SECONDS" ]; then
    sleep 2
    continue
  fi

  if gateway_ok; then
    sleep 10
    continue
  fi

  log "Gateway health check failed; restarting..."
  if [ -n "${gateway_pid:-}" ]; then
    kill "$gateway_pid" >/dev/null 2>&1 || true
    sleep 1
    kill -9 "$gateway_pid" >/dev/null 2>&1 || true
  fi
  start_gateway
  sleep "$GATEWAY_RESTART_BACKOFF_SECONDS"
done

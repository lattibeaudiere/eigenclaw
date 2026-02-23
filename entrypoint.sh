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

# ── 5. Start OpenClaw gateway ─────────────────────────────────────────────────
# TEE requires 0.0.0.0 (not loopback) so EigenCompute can route traffic in
log "Starting OpenClaw gateway on 0.0.0.0:$GATEWAY_PORT..."
exec openclaw gateway run --bind lan --port "$GATEWAY_PORT"

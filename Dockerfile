# EigenClaw — Sovereign AI Agent for EigenCompute TEE
#
# Stack:
#   OpenClaw  = agent runtime  (orchestration, memory, skills, conversation)
#   Chutes    = LLM provider   (OpenClaw's brain — GLM-4.7-TEE by default)
#   Python    = skill runtime  (tx labeler, Chainlink price feeds)
#
# EigenCompute TEE requirements:
#   - Platform: linux/amd64
#   - User: root
#   - Gateway binds to 0.0.0.0 (set in entrypoint.sh)
#
# Required at deploy time (via ecloud compute app deploy --env):
#   CHUTES_API_KEY=<from chutes.ai dashboard>
#
# Deploy:
#   ecloud compute app deploy  →  "Build and deploy from Dockerfile"

FROM --platform=linux/amd64 node:22-bookworm

USER root
WORKDIR /app

# ── System deps ───────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── OpenClaw + long (WhatsApp peer dep) ──────────────────────────────────────
RUN npm install -g openclaw@latest long@latest

# ── Python skill dependencies ─────────────────────────────────────────────────
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY chutes/         ./chutes/
COPY agent/          ./agent/
COPY label_txs.py    .

# ── OpenClaw templates (AGENTS.md etc — required by gateway) ─────────────────
COPY docs/          /app/docs/

# ── Workspace identity + skills ──────────────────────────────────────────────
COPY agent/workspace/ /root/.openclaw/workspace/
COPY agent/skills/    /root/.openclaw/workspace/eigenclaw/skills/


# ── Entrypoint script ─────────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Runtime environment ───────────────────────────────────────────────────────
ENV NODE_ENV=production
ENV NETWORK_PUBLIC=sepolia
# CHUTES_API_KEY + MNEMONIC injected by EigenCompute KMS at deploy time

# OpenClaw gateway port
EXPOSE 18789

CMD ["/entrypoint.sh"]

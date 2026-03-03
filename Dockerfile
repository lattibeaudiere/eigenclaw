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
# Build optimization: Target <600s for EigenCompute verifiable build limit.
# Key tweaks: CPU-only torch (avoids ~2GB CUDA), layer order, aggressive cleanup.
#
# Deploy:
#   ecloud compute app deploy  →  "Build and deploy from Dockerfile"

FROM --platform=linux/amd64 node:22-bookworm

USER root
WORKDIR /app

# ── System deps (single layer, minimal, cleanup) ───────────────────────────────
RUN echo "START: apt" && date && \
    apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && echo "END: apt" && date

# ── Python: CPU-only torch first (avoids CUDA bloat ~2GB → ~200MB) ──────────
# faster-whisper pulls torch; installing torch+cpu first prevents CUDA pull.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt .
RUN echo "START: pip torch" && date && \
    pip3 install --no-cache-dir --break-system-packages \
        torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
    && echo "END: pip torch" && date

RUN echo "START: pip faster-whisper" && date && \
    pip3 install --no-cache-dir --break-system-packages faster-whisper \
    && echo "END: pip faster-whisper" && date

RUN echo "START: pip rest" && date && \
    pip3 install --no-cache-dir --break-system-packages \
        openai python-dotenv requests \
    && rm -rf /root/.cache/pip/* \
    && echo "END: pip rest" && date

# ── OpenClaw + long (WhatsApp peer dep) ──────────────────────────────────────
RUN echo "START: npm" && date && \
    npm install -g --omit=optional openclaw@latest long@latest \
    && echo "END: npm" && date

# ── Application code (last — changes here don't invalidate dep layers) ───────
COPY chutes/         ./chutes/
COPY agent/          ./agent/
COPY label_txs.py    .
COPY docs/           /app/docs/
COPY agent/workspace/ /root/.openclaw/workspace/
COPY agent/skills/   /root/.openclaw/workspace/eigenclaw/skills/

# ── Entrypoint + whisper CLI ──────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    printf '#!/usr/bin/env bash\npython3 /app/agent/scripts/whisper_cli.py "$@"\n' > /usr/local/bin/whisper && chmod +x /usr/local/bin/whisper

# ── Runtime environment ───────────────────────────────────────────────────────
ENV NODE_ENV=production
ENV NETWORK_PUBLIC=sepolia
EXPOSE 18789

CMD ["/entrypoint.sh"]

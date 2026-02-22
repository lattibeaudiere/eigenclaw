# EigenClaw — Sovereign AI Agent

A verifiable, privacy-preserving DeFi AI agent built on three TEE layers.
**Nothing runs on your local machine except the `ecloud` CLI.**

```
┌─────────────────────────────────────────────────────────────────┐
│                     EigenCompute TEE                            │
│                   (Google Cloud Intel TDX)                      │
│                                                                 │
│  ┌──────────────────────┐   ┌──────────────────────────────┐   │
│  │   OpenClaw Gateway   │──▶│   Chutes TEE Inference       │   │
│  │   (Agent "body")     │   │   (Agent "brain")            │   │
│  │                      │   │                              │   │
│  │  Skills:             │   │  Llama 3.2 11B in TEE        │   │
│  │  • tx_labeler        │   │  OpenAI-compatible API       │   │
│  │  • chainlink_price   │   │  Cryptographic attestation   │   │
│  └──────────────────────┘   └──────────────────────────────┘   │
│                │                          ▲                     │
│  ┌─────────────▼──────────────────────────┴──────────────────┐  │
│  │              Python REST API  (server.py)                  │  │
│  │   POST /label   POST /label/batch   GET /health /info      │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         ▲ on-chain attestation proofs (verifiable by anyone)
```

---

## What runs where

| Component | Where it runs | Your machine does |
|-----------|--------------|-------------------|
| OpenClaw gateway | EigenCloud TEE | nothing |
| Chutes LLM inference | Chutes TEE | nothing |
| Docker image build + push | `ecloud` CLI → EigenCloud | one command |
| `ecloud` CLI | Local (already installed) | `ecloud compute app deploy` |

---

## Project Layout

```
EigenClaw/
├── agent/
│   ├── openclaw.json           # OpenClaw config — points LLM at Chutes
│   └── skills/
│       ├── tx_labeler.yaml         # Skill: DeFi tx classification
│       ├── chainlink_price.yaml    # Skill: Chainlink dAPI price feeds
│       └── _chainlink_price_fetch.py  # Python helper for price skill
│
├── chutes/
│   ├── inference_chute.py      # Chute definition — deploy this to Chutes.ai
│   └── client.py               # Inference client (Chutes primary, EigenAI fallback)
│
├── data/
│   └── sample_txs.json         # Example tx inputs
│
├── label_txs.py                # Batch tx labeler CLI
├── server.py                   # HTTP server (runs inside TEE container)
├── test_eigenai.py             # Smoke-test EigenAI directly
│
├── Dockerfile                  # Multi-stage: OpenClaw + Python labeler
├── requirements.txt
├── .env.example                # Template — copy to .env, never commit .env
└── .gitignore
```

---

## Setup

### Step 1 — Get your API keys

**Chutes** (primary brain — TEE LLM inference):
1. Sign up at [chutes.ai](https://chutes.ai)
2. Dashboard → API Keys → copy your key
3. Deploy your inference Chute (GitHub Actions can do this too, or via Chutes UI)

**EigenCloud** (execution environment + fallback inference):
```powershell
ecloud auth generate --store    # stores key locally
ecloud auth whoami              # confirm address
```

**Sepolia ETH** (for testnet deployments — free):
- [Google Cloud Faucet](https://cloud.google.com/application/web3/faucet/ethereum/sepolia)
- [Alchemy Faucet](https://sepoliafaucet.com/)

### Step 4 — Subscribe to EigenCompute

```powershell
ecloud billing subscribe        # opens payment portal — $100 credit covers it
```

### Step 5 — Start Docker Desktop, then deploy

Docker Desktop needs to be running for the `ecloud` CLI to build the image.
The CLI handles the entire build → push → deploy chain — nothing else runs locally.

```powershell
# Start Docker Desktop, then:
ecloud compute app deploy
# When prompted: choose "Build and deploy from Dockerfile"
```

The CLI will:
1. Build the image (targets `linux/amd64` for the TEE)
2. Push it to your Docker registry
3. Deploy it into an EigenCompute TEE
4. Return your live endpoint URL

```powershell
ecloud compute app info         # get your endpoint URL
ecloud compute app logs         # stream logs from the TEE
```

**Alternative — Verifiable Build from source (no local Docker at all):**
If you want EigenCompute to build server-side with cryptographic build provenance:
```powershell
ecloud compute build submit --repo <your-git-repo-url> --commit <sha>
ecloud compute app deploy --verifiable
```
This proves the exact source code → image mapping on-chain.

---

## Using the agent

Once deployed, your agent is reachable at the endpoint from `ecloud compute app info`.

### Label a single transaction
```bash
curl -X POST https://<your-endpoint>/label \
  -H "Content-Type: application/json" \
  -d '{"description": "Calldata redeemDelegations, Aave Mint 128 aArbUSDCn"}'
```

### Label a batch
```bash
curl -X POST https://<your-endpoint>/label/batch \
  -H "Content-Type: application/json" \
  -d '[{"description": "..."}, {"description": "..."}]'
```

### Health check
```bash
curl https://<your-endpoint>/health
# {"status": "ok"}
```

### Get backend info
```bash
curl https://<your-endpoint>/info
# {"backend": "Chutes TEE (...)", "network": "sepolia"}
```

---

## Updating the agent

Make your code changes, then re-run deploy:
```powershell
ecloud compute app deploy       # rebuilds + redeploys
# or to upgrade in-place:
ecloud compute app upgrade
```

---

## Useful commands

```powershell
ecloud compute app list                  # all your apps
ecloud compute app status                # current app status
ecloud compute app logs                  # stream live logs
ecloud compute app terminate             # stop the app
ecloud compute env set sepolia           # switch to testnet
ecloud compute env set mainnet           # switch to mainnet
```

---

## Verify trust (on-chain attestation)

```powershell
ecloud compute app verify                # checks TEE attestation proofs
```

Anyone can verify the agent ran correctly without tampering — the cryptographic
proof is registered on-chain by EigenCompute.

---

## Docs & Support

| Resource | URL |
|---|---|
| EigenCloud docs | [docs.eigencloud.xyz](https://docs.eigencloud.xyz/) |
| EigenCompute quickstart | [docs.eigencloud.xyz/eigencompute/](https://docs.eigencloud.xyz/eigencompute/get-started/quickstart) |
| Chutes docs | [docs.chutes.ai](https://docs.chutes.ai) |
| OpenClaw docs | [docs.openclaw.ai](https://docs.openclaw.ai) |
| EigenLayer Discord | Support channel for EigenCloud issues |

# EigenCloud Deployment Guide

## Current Setup

| Item | Value |
|------|-------|
| App ID | `0x0c976F51abC812e7f2b1767652085b0588556a94` |
| Domain | eigenclaw.xyz |
| Repo | https://github.com/lattibeaudiere/eigenclaw |
| Instance type | g1-standard-4t |
| Gateway port | 18789 |

## Prerequisites

- `ecloud` CLI: `npm install -g @layr-labs/ecloud-cli`
- Docker running
- EigenCloud auth: `ecloud auth login` or `ecloud auth generate --store`
- EigenCompute subscription: `ecloud billing subscribe`
- `.env` with required keys (CHUTES_API_KEY, OPENCLAW_TOKEN, etc.)

## Mainnet Migration

To escape Sepolia-specific issues (409 concurrency blocks, stuck builds, 600s timeouts, 429 throttling), switch to mainnet-alpha. Mainnet uses scaled production infrastructure.

**Before first mainnet deploy**, update `.env`: set `NETWORK_PUBLIC=mainnet` and `EIGENAI_BASE_URL=https://eigenai.eigencloud.xyz/v1` (see `.env.example`).

**Prerequisites (run before first mainnet deploy):**

1. Update CLI: `npm install -g @layr-labs/ecloud-cli`
2. Verify auth: `ecloud auth whoami`
3. Billing: `ecloud billing subscribe` (required for mainnet; $100 credit for new customers)
4. Switch env: `ecloud compute env set mainnet-alpha --yes`
5. Confirm: `ecloud auth whoami` should show Mainnet
6. Fund wallet: ~0.01–0.05 mainnet ETH for deployment gas (real ETH)

**Quick run:** `.\scripts\mainnet-next-steps.ps1` (or `-SkipBilling` to skip the browser step)

**First mainnet deploy** (creates new app; Sepolia app ID is incompatible):

```powershell
ecloud compute app deploy --verifiable `
  --repo https://github.com/lattibeaudiere/eigenclaw `
  --commit 0f0a1f1 `
  --instance-type g1-standard-4t `
  --env-file .env `
  --name eigenclaw `
  --log-visibility private `
  --resource-usage-monitoring enable
```

Capture the **new App ID** from the output.

**Subsequent upgrades** (use new app ID):

```powershell
$env:ECLOUD_APP_ID = "<NEW_APP_ID>"
.\scripts\eigencloud-build-standalone.ps1
```

Or: `.\scripts\eigencloud-build-standalone.ps1 -AppId <NEW_APP_ID>`

**Switch back to Sepolia:** `ecloud compute env set sepolia`

## Option A: Upgrade Existing Pod (EigenClaw only)

Upgrade the current EigenClaw app with latest code:

```powershell
git rev-parse HEAD   # Get 40-char commit SHA
ecloud compute app upgrade 0x0c976F51abC812e7f2b1767652085b0588556a94 `
  --env-file .env `
  --verifiable `
  --repo https://github.com/lattibeaudiere/eigenclaw `
  --commit <40-char-SHA> `
  --instance-type g1-standard-4t `
  --log-visibility private `
  --resource-usage-monitoring enable
```

### Option A1: Standalone build (bypass 429 rate limits)

When the upgrade command hits **429 Too Many Requests** during build polling, use the standalone workflow:

```powershell
# Submit build, poll with backoff, then upgrade when ready
.\scripts\eigencloud-build-standalone.ps1

# Or poll an existing build ID
.\scripts\eigencloud-build-standalone.ps1 -BuildId 3506f95b-34f8-4f53-b326-196f70672b0c

# Submit only, no upgrade at end
.\scripts\eigencloud-build-standalone.ps1 -NoUpgrade
```

Uses exponential backoff (5s → 10s → 20s → 40s, cap 60s) for 429 and status checks.

## Option B: Create New Pod (EigenClaw + Firecrawl)

Firecrawl needs to run somewhere EigenClaw can reach. Two sub-options:

### B1: Firecrawl on external host (Railway, Fly.io, Hetzner)

1. Deploy Firecrawl to Railway/Fly.io/Hetzner (see `firecrawl/README.md`).
2. Get Firecrawl URL (e.g. `https://your-firecrawl.railway.app`).
3. Add to `.env`:
   ```
   FIRECRAWL_BASE_URL=https://your-firecrawl.railway.app
   ```
4. Deploy/upgrade EigenClaw with `--env-file .env` (includes FIRECRAWL_BASE_URL).

### B2: New EigenClaw pod (same code, new instance)

Create a fresh deployment (new App ID):

```powershell
.\scripts\eigencloud-deploy.ps1 -NewPod
```

Or directly:

```powershell
ecloud compute app deploy --env-file .env
```

**If you see prompts:**
- "Build from verifiable source?" → press **Enter** (N) to use local Dockerfile
- "Choose deployment method:" → use **arrow keys** to select "Build and deploy from Dockerfile", then Enter

**To skip prompts**, the script passes `--dockerfile Dockerfile` so it auto-selects build-from-Dockerfile. You may still see:
- App name (type a name or press Enter for default)
- Instance type (already set to g1-standard-4t)

This creates a new pod with a new App ID. Save the new App ID for logs and upgrades.

## Option C: Deploy Firecrawl as separate EigenCloud pod

Firecrawl's full stack (Redis, RabbitMQ, Playwright) is multi-container. EigenCompute runs single containers. To run Firecrawl on EigenCloud you would need a custom Dockerfile that bundles the stack — not provided here. Use B1 (external host) for Firecrawl.

## Test After Deploy

```powershell
.\scripts\eigencloud-test.ps1
```

Or manually:
1. **Logs**: `ecloud compute app logs <APP_ID>`
2. **Gateway**: Open https://eigenclaw.xyz (or your domain)
3. **web_fetch**: Ask agent to fetch a URL; if FIRECRAWL_BASE_URL is set, it uses Firecrawl fallback

## Troubleshooting

### Build timeout (600 seconds)

EigenCompute verifiable builds have a **10-minute (600s) hard limit** on both Sepolia and mainnet-alpha (shared backend). If you see:

```
Build failed: Build step failure: build exceed the duration(seconds:600)
```

the Docker build exceeded that limit. The 429s you may see during polling can occur while a build is already doomed to timeout.

**Fixes to try:**

1. **Optimize the Dockerfile** (this repo already applies these)
   - **CPU-only torch**: Install `torch torchaudio` with `--index-url https://download.pytorch.org/whl/cpu` *before* faster-whisper — avoids ~2GB CUDA download
   - Put slow steps first (apt, pip, npm) so layers cache; copy app code last
   - Remove caches: `rm -rf /var/lib/apt/lists/* /root/.cache/pip/*`
   - Test locally: `docker build --no-cache .` — aim for **&lt;8 minutes** to leave headroom
   - **Profile**: Add `echo "START: step" && date` / `echo "END: step" && date` around slow RUNs; grep build logs to find bottlenecks
   - Or use **GitHub Actions**: push to `main`; the `Build test` workflow runs the build and reports timing

2. **Escalate to EigenCloud**
   - EigenLayer Discord → #eigencloud-support or #dev-help: "Verifiable build hits 600s timeout with faster-whisper + ffmpeg (GH Actions ~2.5 min). Any tips or planned timeout increases?"
   - Share build ID + app ID + Dockerfile snippet

3. **Retry after changes**
   - Old build IDs stay `failed`; focus on new submits after Dockerfile tweaks

### 429 Too Many Requests during polling

When `ecloud compute app upgrade` fails with 429 during build status polling, use the **standalone workflow** (Option A1 above):

```powershell
.\scripts\eigencloud-build-standalone.ps1
```

This submits the build, polls with exponential backoff, and upgrades when the build succeeds.

### 409 Build in progress (stuck)

When you see **409 — "You already have a build in progress"** but `ecloud compute build list` shows only `success`/`failed` (no active builds), the backend may have a stale lock.

**Steps:**
1. Run `ecloud compute build list --json` and check the most recent build IDs and statuses.
2. For any suspected stuck build: `ecloud compute build status <id>` and `ecloud compute build info <id> --json`.
3. Wait 15–30 min; retry `.\scripts\eigencloud-build-standalone.ps1`.
4. **Escalate to EigenCloud support** (EigenLayer Discord → #eigencloud or #support): provide app ID `0x0c976F51abC812e7f2b1767652085b0588556a94`, build IDs from the list, 409 error + timestamp, and ask to clear the lock. No CLI cancel command exists.

# Mainnet migration — run these steps in order
# Usage: .\scripts\mainnet-next-steps.ps1 [-SkipBilling]
#
# Prereqs: npm install -g @layr-labs/ecloud-cli (or use npx)
# Auth: ecloud auth whoami (should show your address)

param([switch]$SkipBilling)

$ErrorActionPreference = "Stop"

# Resolve ecloud — prefer global, fallback to npx
$ecloudCmd = $null
if (Get-Command ecloud -ErrorAction SilentlyContinue) { $ecloudCmd = "ecloud" }
else { $ecloudCmd = "npx @layr-labs/ecloud-cli" }

function Run-Ecloud { Invoke-Expression "$ecloudCmd $args" }

Write-Host "Using: $ecloudCmd" -ForegroundColor Gray

# 1. Switch to mainnet
Write-Host "`n[1/4] Switching to mainnet-alpha..." -ForegroundColor Cyan
Run-Ecloud "compute env set mainnet-alpha --yes"

# 2. Confirm env
Write-Host "`n[2/4] Verifying environment..." -ForegroundColor Cyan
Run-Ecloud "auth whoami"

# 3. Billing (opens browser)
if (-not $SkipBilling) {
    Write-Host "`n[3/4] Billing subscription (opens browser)..." -ForegroundColor Cyan
    Run-Ecloud "billing subscribe"
} else {
    Write-Host "`n[3/4] Skipping billing (run: $ecloudCmd billing subscribe)" -ForegroundColor Gray
}

# 4. Deploy instructions
Write-Host "`n[4/4] First mainnet deploy" -ForegroundColor Cyan
Write-Host "Before running, ensure .env has:" -ForegroundColor Yellow
Write-Host "  NETWORK_PUBLIC=mainnet"
Write-Host "  EIGENAI_BASE_URL=https://eigenai.eigencloud.xyz/v1"
Write-Host ""
Write-Host "Fund wallet with ~0.01-0.05 mainnet ETH, then run:" -ForegroundColor Green
$commit = (git rev-parse HEAD 2>$null)
if (-not $commit) { $commit = "<40-char-SHA>" }
Write-Host @"
$ecloudCmd compute app deploy --verifiable `
  --repo https://github.com/lattibeaudiere/eigenclaw `
  --commit $commit `
  --instance-type g1-standard-4t `
  --env-file .env `
  --name eigenclaw `
  --log-visibility private `
  --resource-usage-monitoring enable
"@ -ForegroundColor White
Write-Host "`nCapture the new App ID for upgrades: .\scripts\eigencloud-build-standalone.ps1 -AppId <NEW_APP_ID>" -ForegroundColor Gray

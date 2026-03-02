# EigenCloud deploy script — upgrade existing pod or deploy new
# Usage: .\scripts\eigencloud-deploy.ps1 [-NewPod] [-Commit <sha>]
#
# For NEW pod: Uses --dockerfile to skip "Build from verifiable source?" and
# auto-select "Build and deploy from Dockerfile". You may still get prompts for
# app name, instance type, etc. — use arrow keys or type to select.

param(
    [switch]$NewPod,
    [string]$Commit = ""
)

$AppId = "0x0c976F51abC812e7f2b1767652085b0588556a94"
$Repo = "https://github.com/lattibeaudiere/eigenclaw"
$InstanceType = "g1-standard-4t"

if (-not (Test-Path .env)) {
    Write-Error ".env not found. Copy .env.example to .env and fill in values."
    exit 1
}

if ($NewPod) {
    Write-Host "Deploying NEW pod (ecloud compute app deploy)..." -ForegroundColor Cyan
    Write-Host "Using --dockerfile to auto-select 'Build from Dockerfile' (skips verifiable prompt)" -ForegroundColor Gray
    ecloud compute app deploy --env-file .env --dockerfile Dockerfile --name eigenclaw --instance-type $InstanceType --log-visibility private --resource-usage-monitoring enable
} else {
    if (-not $Commit) {
        $Commit = (git rev-parse HEAD 2>$null)
        if (-not $Commit) {
            Write-Error "Could not get git commit SHA. Run: git rev-parse HEAD"
            exit 1
        }
    }
    Write-Host "Upgrading existing pod $AppId with commit $Commit..." -ForegroundColor Cyan
    ecloud compute app upgrade $AppId `
        --env-file .env `
        --verifiable `
        --repo $Repo `
        --commit $Commit `
        --instance-type $InstanceType `
        --log-visibility private `
        --resource-usage-monitoring enable
}

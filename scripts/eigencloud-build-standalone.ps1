# EigenCloud standalone build workflow — bypasses upgrade's built-in polling
# Use when 429 rate limits hit during verifiable build polling.
#
# Usage:
#   .\scripts\eigencloud-build-standalone.ps1 [-Commit <sha>] [-BuildId <id>] [-NoUpgrade]
#
# -Commit: Git commit SHA (default: HEAD)
# -BuildId: Poll existing build instead of submitting new one
# -NoUpgrade: Only submit/poll; do not run app upgrade when build succeeds

param(
    [string]$Commit = "",
    [string]$BuildId = "",
    [switch]$NoUpgrade
)

$AppId = "0x0c976F51abC812e7f2b1767652085b0588556a94"
$Repo = "https://github.com/lattibeaudiere/eigenclaw"
$InstanceType = "g1-standard-4t"
$MaxAttempts = 10
$BaseDelaySec = 5
$MaxDelaySec = 60

# Exponential backoff: 5, 10, 20, 40, 60, 60, ...
function Get-BackoffDelay {
    param([int]$Attempt)
    $delay = [Math]::Min($BaseDelaySec * [Math]::Pow(2, $Attempt), $MaxDelaySec)
    $jitter = Get-Random -Minimum -2 -Maximum 3
    return [Math]::Max(1, $delay + $jitter)
}

function Get-BuildStatus {
    param([string]$Id)
    $out = ecloud compute build status $Id --json 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($out -match "429|Too Many Requests") { return @{ status = "rate_limited"; raw = $out } }
        return @{ status = "error"; raw = $out }
    }
    try {
        $json = $out | ConvertFrom-Json
        return @{ status = $json.status; raw = $out }
    } catch {
        return @{ status = "error"; raw = $out }
    }
}

function Get-BuildImageRef {
    param([string]$Id)
    $out = ecloud compute build info $Id --json 2>&1
    if ($LASTEXITCODE -ne 0) { return $null }
    try {
        $json = $out | ConvertFrom-Json
        if ($json.imageUrl) { return $json.imageUrl }
        if ($json.imageDigest) { return $json.imageDigest }
        return $null
    } catch {
        return $null
    }
}

# Resolve build ID
if ($BuildId) {
    Write-Host "Using existing build ID: $BuildId" -ForegroundColor Cyan
} else {
    if (-not (Test-Path .env)) {
        Write-Error ".env not found. Copy .env.example to .env and fill in values."
        exit 1
    }
    if (-not $Commit) {
        $Commit = (git rev-parse HEAD 2>$null)
        if (-not $Commit) {
            Write-Error "Could not get git commit SHA. Run: git rev-parse HEAD"
            exit 1
        }
    }
    Write-Host "Submitting verifiable build (repo=$Repo, commit=$Commit)..." -ForegroundColor Cyan
    $submitOut = ecloud compute build submit --repo $Repo --commit $Commit --no-follow --json 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Build submit failed: $submitOut"
        exit 1
    }
    if ($submitOut -match "([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})") {
        $BuildId = $Matches[1]
    } else {
        Write-Error "Could not parse build ID from: $submitOut"
        exit 1
    }
    Write-Host "Build ID: $BuildId" -ForegroundColor Green
}

# Poll with exponential backoff
$attempt = 0
while ($attempt -lt $MaxAttempts) {
    $result = Get-BuildStatus -Id $BuildId
    $status = $result.status

    if ($status -eq "succeeded") {
        Write-Host "Build succeeded." -ForegroundColor Green
        break
    }
    if ($status -eq "failed") {
        Write-Error "Build failed. Run: ecloud compute build info $BuildId --json"
        exit 1
    }
    if ($status -eq "rate_limited") {
        $delay = Get-BackoffDelay -Attempt $attempt
        Write-Host "429 Too Many Requests. Waiting ${delay}s before retry (attempt $($attempt + 1)/$MaxAttempts)..." -ForegroundColor Yellow
        Start-Sleep -Seconds $delay
        $attempt++
        continue
    }
    if ($status -eq "error") {
        $delay = Get-BackoffDelay -Attempt $attempt
        Write-Host "Status check error. Waiting ${delay}s before retry (attempt $($attempt + 1)/$MaxAttempts)..." -ForegroundColor Yellow
        Write-Host $result.raw
        Start-Sleep -Seconds $delay
        $attempt++
        continue
    }

    # pending, building, etc.
    $delay = Get-BackoffDelay -Attempt $attempt
    Write-Host "Build status: $status. Next check in ${delay}s (attempt $($attempt + 1)/$MaxAttempts)..."
    Start-Sleep -Seconds $delay
    $attempt++
}

if ($attempt -ge $MaxAttempts) {
    Write-Host "Max attempts reached. Build ID: $BuildId" -ForegroundColor Yellow
    Write-Host "Check manually: ecloud compute build status $BuildId"
    Write-Host "When succeeded: ecloud compute app upgrade $AppId --verifiable --image_ref <from-build-info> --instance-type $InstanceType --env-file .env"
    exit 1
}

# Get image ref and upgrade
$imageRef = Get-BuildImageRef -Id $BuildId
if (-not $imageRef) {
    Write-Error "Could not get image_ref from build info. Run: ecloud compute build info $BuildId --json"
    exit 1
}
Write-Host "Image ref: $imageRef" -ForegroundColor Gray

if ($NoUpgrade) {
    Write-Host "Skipping upgrade (--NoUpgrade). To upgrade manually:" -ForegroundColor Cyan
    Write-Host "ecloud compute app upgrade $AppId --verifiable --image_ref `"$imageRef`" --instance-type $InstanceType --env-file .env --log-visibility private --resource-usage-monitoring enable"
    exit 0
}

Write-Host "Upgrading app $AppId with verifiable image..." -ForegroundColor Cyan
ecloud compute app upgrade $AppId `
    --verifiable `
    --image_ref $imageRef `
    --instance-type $InstanceType `
    --env-file .env `
    --log-visibility private `
    --resource-usage-monitoring enable

if ($LASTEXITCODE -ne 0) {
    Write-Error "App upgrade failed."
    exit 1
}
Write-Host "Upgrade complete." -ForegroundColor Green

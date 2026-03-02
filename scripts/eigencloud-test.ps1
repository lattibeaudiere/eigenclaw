# Test EigenCloud deployment
# Usage: .\scripts\eigencloud-test.ps1 [-Domain "eigenclaw.xyz"]

param(
    [string]$Domain = "eigenclaw.xyz"
)

$AppId = "0x0c976F51abC812e7f2b1767652085b0588556a94"

Write-Host "1. Fetching app logs (last 20 lines)..." -ForegroundColor Cyan
ecloud compute app logs $AppId 2>&1 | Select-Object -Last 20

Write-Host "`n2. Testing gateway at https://$Domain ..." -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "https://$Domain" -UseBasicParsing -TimeoutSec 10
    Write-Host "   OK: Gateway responded with status $($r.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "   FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n3. Manual test: Ask your agent (Telegram/dashboard) to fetch https://example.com" -ForegroundColor Cyan
Write-Host "   If FIRECRAWL_BASE_URL is set, web_fetch uses Firecrawl fallback."

# Validate Firecrawl + OpenClaw web_fetch integration (PowerShell)
$FirecrawlUrl = if ($env:FIRECRAWL_BASE_URL) { $env:FIRECRAWL_BASE_URL } else { "http://localhost:3002" }
$GatewayUrl = if ($env:GATEWAY_URL) { $env:GATEWAY_URL } else { "http://localhost:18789" }

Write-Host "1. Testing Firecrawl /v2/scrape directly..."
try {
    $body = '{"url":"https://example.com"}'
    $response = Invoke-RestMethod -Uri "$FirecrawlUrl/v2/scrape" -Method Post -ContentType "application/json" -Body $body
    if ($response.data.markdown -or $response.markdown) {
        Write-Host "   OK: Firecrawl scrape returned content" -ForegroundColor Green
    } else {
        Write-Host "   FAIL: Firecrawl scrape did not return expected content" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "   FAIL: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   Ensure Docker is running and the stack is up: docker compose -f firecrawl/repo/docker-compose.yaml -f docker-compose.yml up -d"
    exit 1
}

Write-Host "2. Testing OpenClaw gateway root..."
try {
    Invoke-WebRequest -Uri $GatewayUrl -UseBasicParsing -TimeoutSec 5 | Out-Null
    Write-Host "   OK: OpenClaw gateway responding" -ForegroundColor Green
} catch {
    Write-Host "   WARN: OpenClaw gateway not reachable (may need auth or different port)" -ForegroundColor Yellow
}

Write-Host "3. Manual web_fetch test: Ask your agent to fetch a URL (e.g. https://example.com)"
Write-Host "   Expected: Clean markdown, fewer failures on JS-heavy pages."

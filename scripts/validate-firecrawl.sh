#!/usr/bin/env bash
# Validate Firecrawl + OpenClaw web_fetch integration.
set -euo pipefail

FIRECRAWL_URL="${FIRECRAWL_BASE_URL:-http://localhost:3002}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:18789}"

echo "1. Testing Firecrawl /v2/scrape directly..."
if curl -sf -X POST "$FIRECRAWL_URL/v2/scrape" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}' | grep -q '"markdown"\|"data"'; then
  echo "   OK: Firecrawl scrape returned content"
else
  echo "   FAIL: Firecrawl scrape did not return expected content"
  exit 1
fi

echo "2. Testing OpenClaw gateway root..."
if curl -sf "$GATEWAY_URL/" >/dev/null; then
  echo "   OK: OpenClaw gateway responding"
else
  echo "   WARN: OpenClaw gateway not reachable (may need auth or different port)"
fi

echo "3. Manual web_fetch test: Ask your agent to fetch a URL (e.g. https://example.com)"
echo "   Expected: Clean markdown, fewer failures on JS-heavy pages."

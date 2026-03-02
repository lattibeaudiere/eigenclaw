#!/usr/bin/env bash
# Clone Firecrawl repo for same-cloud deployment.
# Run from project root, or: bash scripts/setup-firecrawl.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$PROJECT_ROOT/firecrawl/repo"
if [ -d "$REPO_DIR/.git" ]; then
  echo "Firecrawl repo already present at $REPO_DIR"
  (cd "$REPO_DIR" && git pull --rebase 2>/dev/null || true)
else
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone https://github.com/firecrawl/firecrawl.git "$REPO_DIR"
fi
if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/apps/api/.env.example" "$REPO_DIR/.env"
  echo "Created $REPO_DIR/.env — edit BULL_AUTH_KEY and other values as needed."
fi
echo "Firecrawl repo ready at $REPO_DIR"
echo "Start full stack: docker compose -f firecrawl/repo/docker-compose.yaml -f docker-compose.yml up -d"

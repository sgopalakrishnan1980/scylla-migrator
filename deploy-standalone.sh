#!/bin/bash
# Deploy only the config creator web-app (no Spark, Scylla, or migration execution).
# Config files are saved to ./config-output/ on the host.
#
# Usage: ./deploy-standalone.sh
#
# If the container fails: ./deploy-standalone-debug.sh (runs in foreground with verbose logs)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p config-output

echo "=== Scylla Migrator - Config Creator (Standalone) ==="
echo "Building and starting..."
if ! docker compose -f docker-compose.standalone.yml up -d --build; then
  echo ""
  echo "Deploy failed. Relaunch with debug logging:"
  echo "  ./deploy-standalone-debug.sh"
  exit 1
fi

echo ""
echo "=== Ready ==="
echo "Config Creator: http://localhost:5000"
echo "Config output:  $SCRIPT_DIR/config-output/config.yaml"
echo ""
echo "Use the UI to create, verify, and save config. Download for local copy."
echo "Deploy the full stack (docker compose up) when ready to run migrations."
echo ""
echo "If the container fails, run: ./deploy-standalone-debug.sh"

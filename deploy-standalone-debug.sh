#!/bin/bash
# Relaunch the config creator with detailed debug logging (foreground, verbose).
# Use when the container fails after launch to see full logs.
#
# Usage: ./deploy-standalone-debug.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p config-output

echo "=== Scylla Migrator - Config Creator (Debug Mode) ==="
echo "Stopping any existing containers..."
docker compose -f docker-compose.standalone.yml down 2>/dev/null || true

echo ""
echo "Building and launching with debug logging (foreground)..."
echo "Press Ctrl+C to stop."
echo ""

FLASK_DEBUG=1 FLASK_ENV=development \
  docker compose -f docker-compose.standalone.yml up --build 2>&1

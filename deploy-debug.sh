#!/bin/bash
# Relaunch the full Scylla Migrator stack with detailed debug logging (foreground).
# Use when containers fail after launch to see full logs from all services.
#
# Usage: ./deploy-debug.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Scylla Migrator - Full Stack (Debug Mode) ==="
echo "Stopping any existing containers..."
docker compose down 2>/dev/null || true

mkdir -p data/spark-master data/spark-worker data/spark-events

echo ""
echo "Building and launching with debug logging (foreground)..."
echo "All container logs will stream. Press Ctrl+C to stop."
echo ""

docker compose up --build 2>&1

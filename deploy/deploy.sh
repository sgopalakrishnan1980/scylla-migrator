#!/bin/bash
# One-command deploy for Scylla Migrator
# Builds JAR (optional), images, starts docker compose, waits for health

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

BUILD_JAR="${BUILD_JAR:-1}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yaml}"
MAX_WAIT="${MAX_WAIT:-120}"

echo "=== Scylla Migrator Deploy ==="
echo "Project root: $PROJECT_ROOT"

# Build migrator JAR if requested
if [ "$BUILD_JAR" = "1" ] && command -v sbt &>/dev/null; then
  echo "Building migrator JAR..."
  sbt migrator/assembly 2>/dev/null || {
    echo "Warning: sbt build failed or sbt not found. Using existing JAR if present."
  }
fi

# Ensure JAR exists when building
if [ "$BUILD_JAR" = "1" ]; then
  JAR=$(find . -name "*assembly*.jar" 2>/dev/null | head -1)
  if [ -z "$JAR" ]; then
    echo "Error: No migrator JAR found after build. Run: sbt migrator/assembly"
    exit 1
  fi
  echo "Using JAR: $JAR"
fi

# Create data dirs before docker compose (avoids Docker creating them as root)
mkdir -p data/spark-master data/spark-worker data/spark-events

# Build and start
echo "Building Docker images..."
docker compose -f "$COMPOSE_FILE" build

echo "Starting services..."
if ! docker compose -f "$COMPOSE_FILE" up -d; then
  echo ""
  echo "Deploy failed. Relaunch with debug logging (foreground, all logs):"
  echo "  ./deploy-debug.sh"
  exit 1
fi

echo "Waiting 2 minutes for services to stabilize..."
sleep 120

if [ -f "$PROJECT_ROOT/scripts/post-deploy-wait.sh" ]; then
  bash "$PROJECT_ROOT/scripts/post-deploy-wait.sh" || true
fi

echo "Waiting for Spark Master UI (max ${MAX_WAIT}s)..."
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 2>/dev/null | grep -q 200; then
    echo "Spark Master UI is up"
    break
  fi
  sleep 5
  WAITED=$((WAITED + 5))
  echo "  ... ${WAITED}s"
done

if [ $WAITED -ge $MAX_WAIT ]; then
  echo "Warning: Timeout waiting for Spark Master."
  echo "Relaunch with debug logging: ./deploy-debug.sh"
  echo "Or check logs: docker compose logs"
fi

# Fix ownership of data dirs (containers may write as root)
if command -v sudo &>/dev/null && [ -d data ]; then
  sudo chown -R "$(id -u):$(id -g)" data 2>/dev/null || true
fi

echo ""
echo "=== Deploy Complete ==="
echo "Web app:      http://localhost:5000"
echo "Spark Master: http://localhost:8080"
echo "Spark History: http://localhost:18080"
echo "Worker UI:    http://localhost:8081"
echo ""
echo "Run connectivity test: ./run_test.sh"

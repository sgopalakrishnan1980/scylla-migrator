#!/bin/bash
# Get worker logs from the Spark worker container
# Usage: ./get-worker-logs.sh [lines]

LINES="${1:-100}"

if command -v docker &>/dev/null; then
  docker logs --tail "$LINES" spark-worker 2>&1
else
  # When running inside container, try to find Spark logs
  for f in /tmp/spark-*/logs/*.out /spark/logs/*.out 2>/dev/null; do
    [ -f "$f" ] && tail -n "$LINES" "$f" && exit 0
  done
  echo "Worker logs not found"
  exit 1
fi

#!/bin/bash
# Post-deploy: wait for stabilization, then run docker network inspect.
# Used by deploy scripts and EC2 user-data after docker compose up.
# Prints container→IP mapping for reference.

set -e

WAIT_SEC="${POST_DEPLOY_WAIT:-120}"
NETWORK_FILTER="${SPARK_NETWORK_FILTER:-scylla-migrator}"

echo "Waiting ${WAIT_SEC}s for services to stabilize..."
sleep "$WAIT_SEC"

echo "Docker network inspect (container → IP):"
for net in $(docker network ls --format '{{.Name}}' 2>/dev/null | grep -E "${NETWORK_FILTER}" || true); do
  echo "--- Network: $net ---"
  docker network inspect "$net" --format '{{range .Containers}}{{.Name}} -> {{.IPv4Address}}{{println}}{{end}}' 2>/dev/null || true
  # Also show gateway (host IP on bridge)
  GW=$(docker network inspect "$net" --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null || true)
  [ -n "$GW" ] && echo "Gateway (host): $GW"
done

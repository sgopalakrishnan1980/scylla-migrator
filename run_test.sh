docker compose up -d && \
echo "Waiting 30s for ScyllaDB and Spark services to stabilize..." && sleep 30 && \
echo -e "\n--- 1. CONTAINER STATUS (docker ps) ---" && \
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" && \
echo -e "\n--- 2. NETWORK TOPOLOGY (docker network inspect) ---" && \
docker network inspect $(docker network ls -q --filter name=bigdata-net) --format '{{range .Containers}}{{.Name}} -> {{.IPv4Address}}{{end}}' && \
echo -e "\n--- 3. CROSS-NODE NETWORK TESTS (Worker -> Alternator) ---" && \
for node in scylla-node1 scylla-node2 scylla-node3; do \
  echo -n "Testing connectivity from spark-worker to $node:8000... "; \
  docker exec $(docker ps -q --filter name=spark-worker) curl -s -o /dev/null -w "%{http_code}" http://$node:8000 && echo " [OK]"; \
done

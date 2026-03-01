# network_mapping() — GET /api/network-mapping

Returns container→IP mapping from docker network inspect (for UI link host resolution).

## Flow

```
    Client                    network_mapping()           Docker SDK / CLI
       │                          │                              │
       │  GET /api/network-mapping │                              │
       │ ────────────────────────►│                              │
       │                          │  result = {networks: {},      │
       │                          │            ui_base_host}      │
       │                          │                              │
       │                          │  client = _get_docker_client()│
       │                          │  if client:                   │
       │                          │    for net in client.networks:│
       │                          │      if SPARK_NETWORK_FILTER  │
       │                          │        not in net.name: skip  │
       │                          │      containers = net.attrs    │
       │                          │        ["Containers"] → {name: ip}
       │                          │      gateway = IPAM.Config    │
       │                          │      result.networks[net] =   │
       │                          │        {containers, gateway} │
       │                          │                              │
       │                          │  else (fallback):              │
       │                          │    docker network ls           │
       │                          │    docker network inspect NET  │
       │                          │ ─────────────────────────────►│
       │                          │  parse JSON, same structure    │
       │                          │ ◄─────────────────────────────│
       │                          │                              │
       │  JSON                     │                              │
       │ ◄───────────────────────│                              │
```

## Output Structure

```json
{
  "success": true,
  "networks": {
    "scylla-migrator_spark-network": {
      "containers": { "spark-master": "172.18.0.2", "spark-worker": "172.18.0.3", ... },
      "gateway": "172.18.0.1"
    }
  },
  "ui_base_host": "172.18.0.1"
}
```

# worker_logs() — GET /logs/worker

Returns last N lines of Spark worker logs (from Docker or log files).

## Flow

```
    Client                    worker_logs()               _docker_logs / File
       │                          │                              │
       │  GET /logs/worker?lines=N │                              │
       │ ────────────────────────►│                              │
       │                          │  lines = request.args.get(    │
       │                          │    "lines", 100)              │
       │                          │                              │
       │                          │  content = _docker_logs(       │
       │                          │    "spark-worker", tail=lines │
       │                          │  )                            │
       │                          │ ────────────────────────────► │
       │                          │    Docker: container.logs()    │
       │                          │    or: docker logs --tail N   │
       │                          │  content or None              │
       │                          │ ◄─────────────────────────────│
       │                          │                              │
       │                          │  if content:                  │
       │                          │    return {success, content,   │
       │                          │            source: "docker"}  │
       │                          │                              │
       │                          │  # Fallback: log files        │
       │                          │  for pattern in [             │
       │                          │    "/tmp/spark-*/logs/*.out",  │
       │                          │    "/spark/logs/*.out"        │
       │                          │  ]:                           │
       │                          │    content = tail(last N lines)│
       │                          │    return {success, content}  │
       │                          │                              │
       │                          │  return 404 "Worker logs not   │
       │                          │             found"            │
       │                          │                              │
       │  JSON                     │                              │
       │ ◄───────────────────────│                              │
```

## _docker_logs Decision

```
    _docker_logs("spark-worker", tail=N)
              │
              ▼
    Docker SDK available? ──yes──► container.logs(tail=N)
              │
              no
              ▼
    docker logs --tail N spark-worker (subprocess)
```

## Fallback Patterns (no Docker)

- `/tmp/spark-*/logs/*.out` — Spark daemon logs
- `/spark/logs/*.out` — SPARK_HOME/logs (used in ec2-no-docker)

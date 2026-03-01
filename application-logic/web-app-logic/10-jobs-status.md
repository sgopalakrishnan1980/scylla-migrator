# jobs_status() — GET /jobs/status

Returns URLs for Spark UIs (History, Master, Worker).

## Flow

```
    Client                    jobs_status()              _ui_base_host()
       │                          │                              │
       │  GET /jobs/status        │                              │
       │ ────────────────────────►│                              │
       │                          │  base = _ui_base_host()       │
       │                          │ ────────────────────────────► │
       │                          │  "hostname"                   │
       │                          │ ◄─────────────────────────────│
       │                          │                              │
       │                          │  return {                     │
       │                          │    history_url: http://base:18080,
       │                          │    master_url:  http://base:8080,
       │                          │    worker_url:  http://base:8081
       │                          │  }                            │
       │                          │                              │
       │  JSON                     │                              │
       │ ◄───────────────────────│                              │
```

## Outputs

- `{history_url, master_url, worker_url}`

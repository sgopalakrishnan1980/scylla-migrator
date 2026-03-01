# index() — GET /

Renders the main dashboard template with Spark UI links.

## Flow

```
    Client                    index()                    _ui_base_host()
       │                          │                              │
       │  GET /                    │                              │
       │ ────────────────────────►│                              │
       │                          │  base = _ui_base_host()       │
       │                          │ ────────────────────────────►│
       │                          │                              │ EXTERNAL_HOST?
       │                          │                              │ docker network gateway?
       │                          │                              │ request.host?
       │                          │  "hostname"                   │
       │                          │ ◄────────────────────────────│
       │                          │                              │
       │                          │  render_template(              │
       │                          │    "index.html",              │
       │                          │    spark_master_url=...,      │
       │                          │    spark_history_url=...,     │
       │                          │    spark_worker_url=...,      │
       │                          │    standalone_mode=...,       │
       │                          │    config_path=...            │
       │                          │  )                            │
       │                          │                              │
       │  HTML                     │                              │
       │ ◄───────────────────────│                              │
       │                          │                              │
```

## Inputs

- None (environment: STANDALONE_MODE, CONFIG_PATH, SPARK_*_PORT)

## Outputs

- Rendered `index.html` with Spark URLs and config path

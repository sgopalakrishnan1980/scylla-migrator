# Web App Overview

Scylla Migrator Flask web app — config management, validation, job submission, and monitoring.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              USER BROWSER                                         │
│                         http://host:5000                                          │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         │ HTTP
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         FLASK WEB APP (port 5000)                                 │
│                                                                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                 │
│  │ Config Routes   │  │ Job Routes      │  │ API / Logs       │                 │
│  │ /config         │  │ /jobs/submit    │  │ /api/network     │                 │
│  │ /config/parse   │  │ /jobs/status    │  │ /logs/worker     │                 │
│  │ /config/validate│  │                 │  │                  │                 │
│  │ /config/test-   │  │                 │  │                  │                 │
│  │   access        │  │                 │  │                  │                 │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘                 │
│           │                     │                     │                          │
│           └─────────────────────┼─────────────────────┘                          │
│                                 │                                                 │
│                                 ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │                    EXECUTION BACKENDS                                         │ │
│  │                                                                               │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐            │ │
│  │  │ Docker Exec      │  │ Local subprocess │  │ Direct file I/O  │            │ │
│  │  │ (USE_DOCKER_EXEC)│  │ (no Docker)      │  │ config.yaml      │            │ │
│  │  │ docker exec      │  │ spark-submit     │  │                  │            │ │
│  │  │ spark-master     │  │ on host          │  │                  │            │ │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────────────┘            │ │
│  └───────────┼───────────────────┼────────────────────────────────────────────┘ │
└──────────────┼───────────────────┼───────────────────────────────────────────────┘
               │                   │
               ▼                   ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│ DOCKER (if containerized)│  │ SPARK MASTER (7077)       │
│ spark-master container   │  │ spark-submit jobs         │
│ spark-worker container   │  │ Migrator JAR              │
└──────────────────────────┘  └──────────────────────────┘
```

## Request Flow by Endpoint

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ GET /                                                                             │
│   → index() → render index.html (Spark UI links, config path)                     │
├──────────────────────────────────────────────────────────────────────────────────┤
│ GET /config?path=...                                                              │
│   → get_config() → read file → JSON {content, path}                               │
├──────────────────────────────────────────────────────────────────────────────────┤
│ POST /config (body: {content, path, validate_only?})                              │
│   → save_config() → [validate?] → write file → JSON                              │
├──────────────────────────────────────────────────────────────────────────────────┤
│ POST /config/parse (body: {content})                                              │
│   → parse_config() → yaml.safe_load → build form dict → JSON {form, content}      │
├──────────────────────────────────────────────────────────────────────────────────┤
│ POST /config/verify-whitespace (body: {content})                                  │
│   → verify_whitespace() → check tabs/trailing → JSON {issues}                    │
├──────────────────────────────────────────────────────────────────────────────────┤
│ POST /config/test-access (body: {content})                                        │
│   → test_access() → CQL/DynamoDB/S3/Parquet connectivity → JSON {source,target} │
├──────────────────────────────────────────────────────────────────────────────────┤
│ POST /config/execute-create-table (body: {endpoint, payload})                     │
│   → execute_create_table() → HTTP POST to Alternator CreateTable → JSON          │
├──────────────────────────────────────────────────────────────────────────────────┤
│ POST /config/validate (body: {path, include_iam_check})                          │
│   → validate_config_file() → spark-submit --validate-config → JSON              │
├──────────────────────────────────────────────────────────────────────────────────┤
│ POST /jobs/submit (body: {config_path, debug})                                    │
│   → submit_job() → docker exec / subprocess spark-submit (detach) → JSON         │
├──────────────────────────────────────────────────────────────────────────────────┤
│ GET /jobs/status                                                                  │
│   → jobs_status() → JSON {history_url, master_url, worker_url}                   │
├──────────────────────────────────────────────────────────────────────────────────┤
│ GET /api/network-mapping                                                          │
│   → network_mapping() → docker network inspect → JSON {networks, ui_base_host}   │
├──────────────────────────────────────────────────────────────────────────────────┤
│ GET /logs/worker?lines=N                                                          │
│   → worker_logs() → docker logs / file tail → JSON {content, source}             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Spark Job Submission Flow (Docker vs No-Docker)

```
                    POST /jobs/submit
                            │
                            ▼
                   ┌────────────────┐
                   │ STANDALONE_MODE?│
                   └────────┬───────┘
                            │
              ┌─────────────┴─────────────┐
              │ yes                       │ no
              ▼                           ▼
     ┌─────────────────┐       ┌────────────────────────┐
     │ 400 Error        │       │ Config exists?         │
     │ "Use standalone  │       │ JAR exists?           │
     │  for config only"│       └───────────┬────────────┘
     └─────────────────┘                   │
                                           ▼
                              ┌────────────────────────────┐
                              │ USE_DOCKER_EXEC set AND     │
                              │ docker.sock exists?         │
                              └────────────┬───────────────┘
                                           │
                    ┌─────────────────────┴─────────────────────┐
                    │ yes                                        │ no
                    ▼                                            ▼
    ┌──────────────────────────────┐            ┌──────────────────────────────┐
    │ _docker_exec("spark-master",  │            │ subprocess.Popen(            │
    │   spark-submit, detach=True)  │            │   spark-submit,               │
    │                              │            │   start_new_session=True)     │
    │ Returns: {success, pid: 0}   │            │ Returns: {success, pid}       │
    └──────────────────────────────┘            └──────────────────────────────┘
```

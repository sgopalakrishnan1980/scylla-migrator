# submit_job() — POST /jobs/submit

Submits migration job via spark-submit (runs in background).

## Flow

```
    Client                    submit_job()                    Docker / Host
       │                          │                                  │
       │  POST /jobs/submit       │                                  │
       │  body: {config_path,     │                                  │
       │         debug}           │                                  │
       │ ────────────────────────►│                                  │
       │                          │  if STANDALONE_MODE:              │
       │                          │    return 400                     │
       │                          │                                  │
       │                          │  if not Path(config_path).exists():│
       │                          │    return 404                     │
       │                          │                                  │
       │                          │  jar_files = glob(*assembly*.jar)  │
       │                          │  if not jar_files: return 500    │
       │                          │                                  │
       │                          │  base_cmd = [spark-submit,        │
       │                          │    --class Migrator,              │
       │                          │    --master spark://HOST:7077,    │
       │                          │    --conf spark.eventLog...,      │
       │                          │    --conf spark.scylla.config=path│
       │                          │    JAR]                           │
       │                          │  (+ debug log4j opts if debug)    │
       │                          │                                  │
       │                          │  USE_DOCKER_EXEC && socket?       │
       │                          │         │                         │
       │                          │    ┌────┴────┐                     │
       │                          │    │ yes    │ no                  │
       │                          │    ▼        ▼                     │
       │                          │ _docker_exec(          subprocess.Popen(
       │                          │   "spark-master",         base_cmd,
       │                          │   base_cmd,              stdout=DEVNULL,
       │                          │   detach=True           stderr=DEVNULL,
       │                          │ )                        start_new_session=True
       │                          │ ───────────────────────► )        │
       │                          │                                  │
       │                          │  return {success, message, pid}   │
       │                          │                                  │
       │  JSON                     │                                  │
       │ ◄───────────────────────│                                  │
```

## Docker vs No-Docker

```
    USE_DOCKER_EXEC=1 + /var/run/docker.sock
         │
         ▼
    docker exec -d spark-master spark-submit ...
    (pid: 0, process runs inside container)

    No Docker
         │
         ▼
    subprocess.Popen(spark-submit, start_new_session=True)
    (pid: actual process ID on host)
```

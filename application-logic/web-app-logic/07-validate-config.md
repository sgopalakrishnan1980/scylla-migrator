# validate_config_file() — POST /config/validate

Validates config structure via migrator JAR (`--validate-config`). Optionally runs endpoint checks.

## Flow

```
    Client                    validate_config_file()        _run_spark_submit
       │                          │                              │
       │  POST /config/validate   │                              │
       │  body: {path,            │                              │
       │         include_iam_     │                              │
       │         check}           │                              │
       │ ────────────────────────►│                              │
       │                          │  if STANDALONE_MODE:          │
       │                          │    return 400                 │
       │                          │                              │
       │                          │  content = Path(path).read   │
       │                          │  if empty: return 400        │
       │                          │                              │
       │                          │  run_validate_config(...)    │
       │                          │ ───────────────────────────► │
       │                          │                              │
       │                          │    tmp_path = /app/_validate_*.yaml
       │                          │    tmp_path.write_text(content)
       │                          │    _run_spark_submit(         │
       │                          │      ["--validate-config"],  │
       │                          │      tmp_path                 │
       │                          │    )                          │
       │                          │    ─────────────────────────►│
       │                          │                              │  docker exec
       │                          │                              │  spark-master
       │                          │                              │  spark-submit
       │                          │                              │  --validate-config
       │                          │    (code, out, err)           │
       │                          │ ◄─────────────────────────────│
       │                          │                              │
       │                          │    if code != 0:              │
       │                          │      return {success:false}   │
       │                          │                              │
       │                          │    if include_iam_check:     │
       │                          │      access = _test_access_impl(cfg)
       │                          │      result["accessCheck"] = access
       │                          │                              │
       │                          │    tmp_path.unlink()          │
       │                          │    return result              │
       │                          │ ◄────────────────────────────│
       │                          │                              │
       │  JSON                     │                              │
       │ ◄───────────────────────│                              │
```

## _run_spark_submit Decision

```
                    _run_spark_submit(cmd_extra, config_path)
                                     │
                                     ▼
                    USE_DOCKER_EXEC && docker.sock exists?
                                     │
              ┌──────────────────────┴──────────────────────┐
              │ yes                                         │ no
              ▼                                             ▼
    _docker_exec("spark-master",                   subprocess.run(
      ["spark-submit", "--class",                    ["spark-submit", ...],
      "Migrator", "--master",                       capture_output=True
      "spark://HOST:7077", ...],
      detach=False
    )
```

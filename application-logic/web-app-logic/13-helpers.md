# Helper Functions — Flow Diagrams

Key internal helpers used across routes.

## _ui_base_host()

Resolves the hostname to use for Spark UI links (browser-facing URLs).

```
    _ui_base_host()
           │
           ▼
    EXTERNAL_HOST env set?
           │
     ┌─────┴─────┐
     │ yes      │ no
     ▼          ▼
  return     Docker client?
  EXTERNAL       │
  _HOST     ┌────┴────┐
            │ yes     │ no
            ▼         ▼
    _docker_network_   request.host
    _gateway()         (from Flask)?
            │              │
            ▼              ▼
    gateway or        request.host or
    "localhost"       "localhost"
```

## _get_docker_client()

```
    _get_docker_client()
           │
           ▼
    _docker_client cached?  ──yes──► return it
           │
           no
           ▼
    docker_sdk imported AND /var/run/docker.sock exists?
           │
     ┌─────┴─────┐
     │ no        │ yes
     ▼           ▼
  return None   DockerClient(base_url=...).ping()
                    │
               ┌────┴────┐
               │ ok      │ fail
               ▼         ▼
          cache &    _docker_client=None
          return     return None
```

## _docker_exec(container_name, cmd, detach)

```
    _docker_exec("spark-master", [...], detach=True/False)
           │
           ▼
    client = _get_docker_client()
           │
     ┌─────┴─────┐
     │ client    │ no client
     ▼           ▼
    container.exec_run(cmd,   _docker_via_cli(...)
      detach=detach)         subprocess: docker exec
           │                     [ -d ] container cmd
           ▼
    return (exit_code, stdout, stderr)
      or (0, None, None) if detach
```

## _run_spark_submit(cmd_extra, config_path)

```
    _run_spark_submit(["--validate-config"], "/tmp/config.yaml")
           │
           ▼
    jars_dir = /jars or /app/migrator/target/scala-2.13
    jar = glob(*assembly*.jar)[0]
           │
           ▼
    base_cmd = [spark-submit, --class Migrator,
                --master spark://HOST:7077,
                --conf spark.scylla.config=path,
                jar] + cmd_extra
           │
           ▼
    USE_DOCKER_EXEC && docker.sock?
           │
     ┌─────┴─────┐
     │ yes       │ no
     ▼           ▼
    _docker_exec(     subprocess.run(
      "spark-master",   base_cmd,
      base_cmd,         capture_output=True
      detach=False      timeout=120
    )                )
           │
           ▼
    return (returncode, stdout, stderr)
```

## _test_access_impl(cfg)

Same logic as `test_access()` but called with parsed config dict (used by `run_validate_config` when include_iam_check=True). Routes by source/target type to CQL, Alternator, DynamoDB AWS, S3, Parquet helpers.

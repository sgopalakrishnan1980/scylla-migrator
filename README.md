# ScyllaDB Migrator (Fork)

This is a **fork** of the [ScyllaDB Migrator](https://github.com/scylladb/scylla-migrator) by ScyllaDB. The ScyllaDB Migrator is a Spark application that migrates data to ScyllaDB from CQL-compatible or DynamoDB-compatible databases.

> **Original repository:** https://github.com/scylladb/scylla-migrator

---

## Major Changes from the Original

- **Web app** — A Flask-based UI for config creation, validation, job submission, and monitoring (not present in the upstream repo).
- **Build scripts** — Uses `build.sh` and `docker-build-jar.sh` instead of the upstream `Makefile` (`make build`, `make docker-build-jar`).
- **Standalone mode** — The web app can run without Spark or Scylla, for config-only workflows.
- **AWS deployment** — CloudFormation and Terraform for EC2; runs Spark + web app only (no Alternator — connect to your own target).
- **SSM for EC2** — IAM role with `AmazonSSMManagedInstanceCore` by default; connect via `aws ssm start-session` without SSH keys or port 22.
- **Debug tooling** — `deploy-debug.sh` and `deploy-standalone-debug.sh` for foreground/debug deployments.

---

## Additional Features

- **Config Creator (Standalone)** — Deploy only the web app to create and manage migration configs without Spark or Scylla.
- **Config whitespace verification** — Detects tabs and trailing spaces in config YAML that can cause Spark errors.
- **Source/target access checks** — UI-driven connectivity tests for CQL, Parquet, DynamoDB, S3, and Alternator before migration.
- **CreateTable via UI** — Execute DynamoDB CreateTable against Alternator from the web app (e.g., for table-not-found recovery).
- **Known-issues workarounds** — In-app guidance for common Alternator and DynamoDB S3 export issues (see scylla-migrator GitHub issues).
- **EC2 deployment** — CloudFormation and Terraform; `docker-compose.ec2.yml` runs Spark + web app only (config, Spark setup, web UI). No Alternator; connect to your own target. See `docs/EC2-DEPLOYMENT.md`.
- **SSM Session Manager access** — Connect to EC2 via `aws ssm start-session --target <instance-id>` or SSH-over-SSM (no keys, no port 22). See [SSM / SSH-over-SSM](docs/EC2-DEPLOYMENT.md#ssm--ssh-over-ssm).

---

## Documentation

- **Upstream docs:** https://migrator.docs.scylladb.com
- **EC2 deployment (this fork):** [docs/EC2-DEPLOYMENT.md](docs/EC2-DEPLOYMENT.md) — CloudFormation, Terraform, SSM access

## Config Creator (Standalone)

Deploy only the web-app for creating a migration config without Spark or Scylla:

```bash
./deploy-standalone.sh
```

Or with Docker directly:

```bash
mkdir -p config-output
docker run -d -p 5000:5000 -v $(pwd)/config-output:/app -e STANDALONE_MODE=1 \
  $(docker build -q web-app)
```

Then open http://localhost:5000. Use the UI to create, verify whitespace, check source/target access, and save or download your config. Config files are saved to `./config-output/config.yaml`. Deploy the full stack when ready to run migrations.

**If the container fails:** Relaunch with debug logging (foreground, verbose):
```bash
./deploy-standalone-debug.sh
```

## Building

To test a custom version of the migrator that has not been [released](https://github.com/scylladb/scylla-migrator/releases), you can build it yourself by cloning this Git repository and following the steps below:

Build locally:
1. Make sure the Java 8+ JDK and `sbt` are installed on your machine.
2. Export the `JAVA_HOME` environment variable with the path to the JDK installation.
3. Run `build.sh`

Build Locally in Docker:
1. Run `docker-build-jar.sh` to build locally using Docker.

Both options will produce the .jar file to use in `spark-submit` command at path `migrator/target/scala-2.13/scylla-migrator-assembly.jar`.

## Contributing

Please refer to the file [CONTRIBUTING.md](/CONTRIBUTING.md).

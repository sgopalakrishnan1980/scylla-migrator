# ScyllaDB Migrator

The ScyllaDB Migrator is a Spark application that migrates data to ScyllaDB from CQL-compatible or DynamoDB-compatible databases.

## Documentation

See https://migrator.docs.scylladb.com.

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
1. Run `docker-build-jar.sh` to build locally using docker or
   
Both options will produce the .jar file to use in `spark-submit` command at path `migrator/target/scala-2.13/scylla-migrator-assembly.jar`.

## Contributing

Please refer to the file [CONTRIBUTING.md](/CONTRIBUTING.md).

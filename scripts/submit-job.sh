#!/bin/bash
# Submit a migration job to the Spark cluster
# Usage: ./submit-job.sh [config.yaml]
# Set DEBUG=1 to enable max debug logging on driver and executors

set -e

CONFIG_PATH="${1:-/app/config.yaml}"
SPARK_MASTER="${SPARK_MASTER:-spark://spark-master:7077}"
JARS_DIR="${JARS_DIR:-/jars}"
DEBUG="${DEBUG:-0}"

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Error: Config file not found: $CONFIG_PATH"
  exit 1
fi

JAR=$(find "$JARS_DIR" -name "*assembly*.jar" 2>/dev/null | head -1)
if [ -z "$JAR" ]; then
  JARS_DIR="/app/migrator/target/scala-2.13"
  JAR=$(find "$JARS_DIR" -name "*assembly*.jar" 2>/dev/null | head -1)
fi
if [ -z "$JAR" ]; then
  echo "Error: Migrator JAR not found. Build with: sbt migrator/assembly"
  exit 1
fi

EXTRA_CONF=()
if [ "$DEBUG" = "1" ]; then
  LOG4J_CONF="-Dlog4j2.configurationFile=file:/spark/conf/log4j2-debug.properties"
  EXTRA_CONF=(--conf "spark.driver.extraJavaOptions=$LOG4J_CONF" --conf "spark.executor.extraJavaOptions=$LOG4J_CONF")
  echo "Debug logging enabled"
fi

echo "Submitting migration job with config: $CONFIG_PATH"
exec spark-submit \
  --class com.scylladb.migrator.Migrator \
  --master "$SPARK_MASTER" \
  --conf spark.eventLog.enabled=true \
  --conf spark.scylla.config="$CONFIG_PATH" \
  "${EXTRA_CONF[@]}" \
  "$JAR"

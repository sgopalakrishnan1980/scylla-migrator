package com.scylladb.migrator

import com.scylladb.migrator.alternator.AlternatorMigrator
import com.scylladb.migrator.config._
import com.scylladb.migrator.scylla.ScyllaMigrator
import org.apache.log4j.{ Level, LogManager, Logger }
import org.apache.spark.sql._

object Migrator {
  val log = LogManager.getLogger("com.scylladb.migrator")

  def main(args: Array[String]): Unit = {
    implicit val spark: SparkSession = SparkSession
      .builder()
      .appName("scylla-migrator")
      .config("spark.task.maxFailures", "1024")
      .config("spark.stage.maxConsecutiveAttempts", "60")
      .config("spark.streaming.stopGracefullyOnShutdown", "true")
      .getOrCreate()

    Logger.getRootLogger.setLevel(Level.WARN)
    log.setLevel(Level.INFO)
    Logger.getLogger("org.apache.spark.scheduler.TaskSetManager").setLevel(Level.WARN)
    Logger.getLogger("com.datastax.spark.connector.cql.CassandraConnector").setLevel(Level.WARN)

    log.info(s"ScyllaDB Migrator ${BuildInfo.version}")

    val configPath = spark.conf.get("spark.scylla.config")

    if (args.contains("--validate-config")) {
      MigratorConfig.loadFromPath(configPath) match {
        case Right(cfg) =>
          log.info("Config validation successful.")
          log.info(s"Source: ${cfg.source.getClass.getSimpleName}, Target: ${cfg.target.getClass.getSimpleName}")
          spark.stop()
          return
        case Left(err) =>
          log.error(s"Config validation failed: $err")
          spark.stop()
          sys.error(err)
      }
    }

    val migratorConfig = MigratorConfig.loadFrom(configPath)

    log.info(s"Loaded config: ${migratorConfig}")

    try {
      (migratorConfig.source, migratorConfig.target) match {
        case (cassandraSource: SourceSettings.Cassandra, scyllaTarget: TargetSettings.Scylla) =>
          val sourceDF = readers.Cassandra.readDataframe(
            spark,
            cassandraSource,
            cassandraSource.preserveTimestamps,
            migratorConfig.getSkipTokenRangesOrEmptySet)
          ScyllaMigrator.migrate(migratorConfig, scyllaTarget, sourceDF)
        case (parquetSource: SourceSettings.Parquet, scyllaTarget: TargetSettings.Scylla) =>
          readers.Parquet.migrateToScylla(migratorConfig, parquetSource, scyllaTarget)(spark)
        case (dynamoSource: SourceSettings.DynamoDB, alternatorTarget: TargetSettings.DynamoDB) =>
          AlternatorMigrator.migrateFromDynamoDB(dynamoSource, alternatorTarget, migratorConfig)
        case (
            s3Source: SourceSettings.DynamoDBS3Export,
            alternatorTarget: TargetSettings.DynamoDB) =>
          AlternatorMigrator.migrateFromS3Export(s3Source, alternatorTarget, migratorConfig)
        case _ =>
          sys.error("Unsupported combination of source and target.")
      }
    } finally {
      spark.stop()
    }
  }

}

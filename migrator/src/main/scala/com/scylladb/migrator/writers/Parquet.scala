package com.scylladb.migrator.writers

import com.datastax.spark.connector.rdd.partitioner.{
  CassandraPartition,
  CqlTokenRange
}
import com.datastax.spark.connector.rdd.partitioner.dht.Token
import com.scylladb.migrator.SavepointsManager
import com.scylladb.migrator.config.{
  MigratorConfig,
  SourceSettings,
  TargetSettings
}
import com.scylladb.migrator.scylla.SourceDataFrame
import org.apache.log4j.{LogManager, Logger}
import org.apache.spark.sql.{DataFrame, Row, SparkSession}
import org.apache.spark.util.CollectionAccumulator

import scala.jdk.CollectionConverters._
import scala.util.control.NonFatal

object Parquet {
  private val DefaultFileSizeMB = 128
  val log: Logger = LogManager.getLogger("com.scylladb.migrator.writer.Parquet")

  final case class CompletedTokenRange(start: Token[_], end: Token[_])
      extends Serializable

  private class TokenRangeSavepointsManager(
      migratorConfig: MigratorConfig,
      accumulator: CollectionAccumulator[CompletedTokenRange])
      extends SavepointsManager(migratorConfig) {
    override def describeMigrationState(): String =
      s"Ranges added: ${completedRanges.size}"

    override def updateConfigWithMigrationState(): MigratorConfig =
      migratorConfig.copy(
        skipTokenRanges =
          Some(migratorConfig.getSkipTokenRangesOrEmptySet ++ completedRanges))

    private def completedRanges: Set[(Token[_], Token[_])] =
      accumulator.value.asScala.iterator.map(r => (r.start, r.end)).toSet
  }

  private def configureHadoopCredentials(spark: SparkSession,
                                         target: TargetSettings.Parquet): Unit =
    target.finalCredentials.foreach { credentials =>
      log.info("Loaded AWS credentials from config file for Parquet target")
      target.region.foreach { region =>
        spark.sparkContext.hadoopConfiguration.set("fs.s3a.endpoint.region",
                                                   region)
      }
      spark.sparkContext.hadoopConfiguration
        .set("fs.s3a.access.key", credentials.accessKey)
      spark.sparkContext.hadoopConfiguration
        .set("fs.s3a.secret.key", credentials.secretKey)
      credentials.maybeSessionToken.foreach { sessionToken =>
        spark.sparkContext.hadoopConfiguration.set(
          "fs.s3a.aws.credentials.provider",
          "org.apache.hadoop.fs.s3a.TemporaryAWSCredentialsProvider")
        spark.sparkContext.hadoopConfiguration.set("fs.s3a.session.token",
                                                   sessionToken)
      }
    }

  private def extractTokenRanges(
      df: DataFrame): Map[Int, Seq[CompletedTokenRange]] =
    df.rdd.partitions.map { partition =>
      val ranges =
        partition
          .asInstanceOf[CassandraPartition[_, _]]
          .tokenRanges
          .asInstanceOf[Vector[CqlTokenRange[_, _]]]
          .map(tr =>
            CompletedTokenRange(tr.range.start.asInstanceOf[Token[_]],
                                tr.range.end.asInstanceOf[Token[_]]))
      partition.index -> ranges
    }.toMap

  private def trackCompletedPartitions(
      df: DataFrame,
      tokenRangesByPartition: Map[Int, Seq[CompletedTokenRange]],
      accumulator: Option[CollectionAccumulator[CompletedTokenRange]])(
      implicit spark: SparkSession): DataFrame =
    accumulator match {
      case None => df
      case Some(acc) =>
        val tracked = df.rdd.mapPartitionsWithIndex { (partitionIndex, rows) =>
          val ranges = tokenRangesByPartition.getOrElse(partitionIndex, Nil)
          if (ranges.isEmpty) rows
          else
            new Iterator[Row] {
              private var marked = false

              private def markComplete(): Unit =
                if (!marked) {
                  ranges.foreach(acc.add)
                  marked = true
                }

              override def hasNext: Boolean = {
                val nextExists = rows.hasNext
                if (!nextExists) {
                  markComplete()
                }
                nextExists
              }

              override def next(): Row = {
                val row = rows.next()
                if (!rows.hasNext) {
                  markComplete()
                }
                row
              }
            }
        }
        spark.createDataFrame(tracked, df.schema)
    }

  def writeDataframe(
      target: TargetSettings.Parquet,
      df: DataFrame,
      tokenRangesByPartition: Map[Int, Seq[CompletedTokenRange]],
      accumulator: Option[CollectionAccumulator[CompletedTokenRange]])(
      implicit spark: SparkSession): Unit = {
    val fileSizeMB = target.fileSizeMB.getOrElse(DefaultFileSizeMB)
    val fileSizeBytes = fileSizeMB.toLong * 1024L * 1024L
    configureHadoopCredentials(spark, target)
    spark.sparkContext.hadoopConfiguration
      .set("parquet.block.size", fileSizeBytes.toString)

    val trackedDf =
      trackCompletedPartitions(df, tokenRangesByPartition, accumulator)
    log.info(
      s"Writing ${trackedDf.rdd.getNumPartitions} partitions to Parquet path ${target.path} with target file size ${fileSizeMB}MB")

    trackedDf.write
      .mode("append")
      .option("compression", "snappy")
      .option("parquet.block.size", fileSizeBytes.toString)
      .parquet(target.path)
  }

  def migrateFromCassandra(
      migratorConfig: MigratorConfig,
      source: SourceSettings.Cassandra,
      target: TargetSettings.Parquet,
      sourceDF: SourceDataFrame)(implicit spark: SparkSession): Unit = {
    log.info(
      s"Starting Cassandra/Scylla -> Parquet migration from ${source.keyspace}.${source.table}")
    log.info("Created source dataframe; resulting schema:")
    sourceDF.dataFrame.printSchema()

    val tokenRangesByPartition = extractTokenRanges(sourceDF.dataFrame)
    val maybeAccumulator =
      if (!sourceDF.savepointsSupported) None
      else {
        val acc = spark.sparkContext.collectionAccumulator[CompletedTokenRange](
          "Token ranges written to parquet")
        Some(acc)
      }
    val maybeSavepointsManager =
      maybeAccumulator.map(new TokenRangeSavepointsManager(migratorConfig, _))

    try {
      writeDataframe(target,
                     sourceDF.dataFrame,
                     tokenRangesByPartition,
                     maybeAccumulator)
    } catch {
      case NonFatal(e) =>
        log.error(
          "Caught error while writing the DataFrame to Parquet. Will create a savepoint before exiting",
          e)
        throw e
    } finally {
      for (savepointsManager <- maybeSavepointsManager) {
        savepointsManager.dumpMigrationState("final")
        savepointsManager.close()
      }
    }
  }
}

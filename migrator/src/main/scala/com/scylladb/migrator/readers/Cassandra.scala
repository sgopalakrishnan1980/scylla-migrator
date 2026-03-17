package com.scylladb.migrator.readers

import com.datastax.spark.connector._
import com.datastax.spark.connector.cql.{Schema, TableDef}
import com.datastax.spark.connector.rdd.ReadConf
import com.datastax.spark.connector.rdd.partitioner.dht.Token
import com.datastax.spark.connector.types.CassandraOption
import com.scylladb.migrator.Connectors
import com.scylladb.migrator.config.{CopyType, SourceSettings}
import org.apache.log4j.LogManager
import org.apache.spark.rdd.RDD
import org.apache.spark.sql.cassandra.{CassandraSQLRow, DataTypeConverter}
import org.apache.spark.sql.types.{
  IntegerType,
  LongType,
  StructField,
  StructType
}
import org.apache.spark.sql.{DataFrame, Encoders, Row, SparkSession}
import org.apache.spark.unsafe.types.UTF8String
import com.datastax.oss.driver.api.core.ConsistencyLevel
import com.scylladb.migrator.scylla.SourceDataFrame

import scala.collection.immutable.ArraySeq
import scala.collection.mutable.ArrayBuffer

object Cassandra {
  val log = LogManager.getLogger("com.scylladb.migrator.readers.Cassandra")

  private case class AutoTuning(localShards: Option[Int],
                                nodeCount: Int,
                                estimatedTableBytes: Option[Long],
                                tunedSource: SourceSettings.Cassandra)

  case class Selection(columnRefs: List[ColumnRef],
                       schema: StructType,
                       timestampColumns: Option[TimestampColumns])

  def determineCopyType(
      tableDef: TableDef,
      preserveTimesRequest: Boolean): Either[Throwable, CopyType] =
    if (tableDef.columnTypes.exists(_.isCollection) && preserveTimesRequest)
      Left(new Exception(
        "TTL/Writetime preservation is unsupported for tables with collection types. Please check in your config the option 'preserveTimestamps' and set it to false to continue."))
    else if (preserveTimesRequest && tableDef.regularColumns.nonEmpty)
      Right(CopyType.WithTimestampPreservation)
    else if (preserveTimesRequest && tableDef.regularColumns.isEmpty) {
      log.warn(
        "No regular columns in the table - disabling timestamp preservation")
      Right(CopyType.NoTimestampPreservation)
    } else Right(CopyType.NoTimestampPreservation)

  def createSelection(tableDef: TableDef,
                      origSchema: StructType,
                      preserveTimes: Boolean): Either[Throwable, Selection] =
    determineCopyType(tableDef, preserveTimes) map {
      case CopyType.WithTimestampPreservation =>
        val columnRefs =
          tableDef.partitionKey.map(_.ref) ++
            tableDef.clusteringColumns.map(_.ref) ++
            tableDef.regularColumns.flatMap { column =>
              val colName = column.columnName

              List(
                column.ref,
                colName.ttl as s"${colName}_ttl",
                colName.writeTime as s"${colName}_writetime"
              )
            }

        log.info("ColumnRefs generated for selection:")
        log.info(columnRefs.mkString("\n"))

        val schema = StructType(for {
          origField <- origSchema.fields
          isRegular = tableDef.regularColumns.exists(
            _.ref.columnName == origField.name)
          field <- if (isRegular)
            List(origField,
                 StructField(s"${origField.name}_ttl", IntegerType, true),
                 StructField(s"${origField.name}_writetime", LongType, true))
          else List(origField)
        } yield field)

        log.info("Schema generated with TTLs and Writetimes:")
        schema.printTreeString()

        Selection(columnRefs.toList,
                  schema,
                  Some(TimestampColumns("ttl", "writetime")))

      case CopyType.NoTimestampPreservation =>
        // We're not using the `tableDef.allColumns` property here in order to generate
        // a schema that is consistent with the timestamp preservation case; the ordering
        // must be (partition keys, clustering keys, regular columns).
        val columnRefs = (tableDef.partitionKey.map(_.ref) ++
          tableDef.clusteringColumns.map(_.ref) ++
          tableDef.regularColumns.map(_.ref)).toList

        log.info("ColumnRefs generated for selection:")
        log.info(columnRefs.mkString("\n"))
        log.info("Schema generated:")
        origSchema.printTreeString()

        Selection(columnRefs, origSchema, None)
    }

  def explodeRow(row: Row,
                 schema: StructType,
                 primaryKeyOrdinals: Map[String, Int],
                 regularKeyOrdinals: Map[String, (Int, Int, Int)]) =
    if (regularKeyOrdinals.isEmpty) List(row)
    else {
      val rowTimestampsToFields =
        regularKeyOrdinals
          .map {
            case (fieldName, (ordinal, ttlOrdinal, writetimeOrdinal)) =>
              (fieldName,
               if (row.isNullAt(ordinal)) CassandraOption.Null
               else CassandraOption.Value(row.get(ordinal)),
               if (row.isNullAt(ttlOrdinal)) None
               else Some(row.getInt(ttlOrdinal)),
               if (row.isNullAt(writetimeOrdinal)) None
               else Some(row.getLong(writetimeOrdinal)))
          }
          .groupBy {
            case (fieldName, value, ttl, writetime) => (ttl, writetime)
          }
          .view
          .mapValues(
            _.map {
              case (fieldName, value, _, _) => fieldName -> value
            }.toMap
          )
          .toMap

      // This is an optimisation to avoid unnecessary inserts and tombstones:
      // If there are multiple rows to insert, remove the row containing NULLs
      // (since those will be "inserted" as a result of inserting the remaining rows)
      val timestampsToFields =
        if (rowTimestampsToFields.size > 1)
          rowTimestampsToFields.-((None, None))
        else rowTimestampsToFields

      timestampsToFields
        .map {
          case ((ttl, writetime), fields) =>
            val newValues = schema.fields.map { field =>
              primaryKeyOrdinals
                .get(field.name)
                .flatMap { ord =>
                  if (row.isNullAt(ord)) None
                  else Some(row.get(ord))
                }
                .getOrElse(fields.getOrElse(field.name, CassandraOption.Unset))
            } ++ Seq(ttl.getOrElse(0L),
                     writetime.getOrElse(CassandraOption.Unset))

            Row(ArraySeq.unsafeWrapArray(newValues): _*)
        }
    }

  def indexFields(currentFieldNames: List[String],
                  origFieldNames: List[String],
                  tableDef: TableDef) = {
    val fieldIndices = currentFieldNames.zipWithIndex.toMap
    val primaryKeyIndices =
      (for {
        origFieldName <- origFieldNames
        if tableDef.primaryKey.exists(_.ref.columnName == origFieldName)
        index <- fieldIndices.get(origFieldName)
      } yield origFieldName -> index).toMap

    val regularKeyIndices =
      (for {
        origFieldName <- origFieldNames
        if tableDef.regularColumns.exists(_.ref.columnName == origFieldName)
        fieldIndex <- fieldIndices.get(origFieldName)
        ttlIndex <- fieldIndices.get(s"${origFieldName}_ttl")
        writetimeIndex <- fieldIndices.get(s"${origFieldName}_writetime")
      } yield origFieldName -> (fieldIndex, ttlIndex, writetimeIndex)).toMap

    (primaryKeyIndices, regularKeyIndices)
  }

  def adjustDataframeForTimestampPreservation(
      spark: SparkSession,
      df: DataFrame,
      timestampColumns: Option[TimestampColumns],
      origSchema: StructType,
      tableDef: TableDef): DataFrame =
    timestampColumns match {
      case None => df
      case Some(TimestampColumns(ttl, writeTime)) =>
        val (primaryKeyOrdinals, regularKeyOrdinals) = indexFields(
          df.schema.fields.map(_.name).toList,
          origSchema.fields.map(_.name).toList,
          tableDef)

        val broadcastPrimaryKeyOrdinals =
          spark.sparkContext.broadcast(primaryKeyOrdinals)
        val broadcastRegularKeyOrdinals =
          spark.sparkContext.broadcast(regularKeyOrdinals)
        val broadcastSchema = spark.sparkContext.broadcast(origSchema)
        val finalSchema = StructType(
          origSchema.fields ++
            Seq(StructField(ttl, IntegerType, true),
                StructField(writeTime, LongType, true))
        )

        log.info("Schema that'll be used for writing to Scylla:")
        log.info(finalSchema.treeString)

        df.flatMap {
          explodeRow(_,
                     broadcastSchema.value,
                     broadcastPrimaryKeyOrdinals.value,
                     broadcastRegularKeyOrdinals.value)
        }(Encoders.row(finalSchema))

    }

  private def queryLocalShardCount(
      connector: com.datastax.spark.connector.cql.CassandraConnector)
    : Option[Int] =
    connector.withSessionDo { session =>
      List(
        "SELECT shards_count FROM system.local",
        "SELECT shards FROM system.local"
      ).iterator
        .map { query =>
          try {
            Option(session.execute(query).one()).map { row =>
              if (row.isNull(0)) 0 else row.getInt(0)
            }
          } catch {
            case _: Throwable => None
          }
        }
        .collectFirst { case Some(value) if value > 0 => value }
    }

  private def queryEstimatedTableBytes(
      connector: com.datastax.spark.connector.cql.CassandraConnector,
      source: SourceSettings.Cassandra): Option[Long] =
    connector.withSessionDo { session =>
      try {
        val stmt = session.prepare(
          "SELECT mean_partition_size, partitions_count FROM system.size_estimates WHERE keyspace_name = ? AND table_name = ?")
        val rows = session
          .execute(stmt.bind(source.keyspace, source.table))
          .all()
          .iterator()
        var total: Long = 0L
        while (rows.hasNext) {
          val row = rows.next()
          val mean =
            if (row.isNull("mean_partition_size")) 0L
            else row.getLong("mean_partition_size")
          val count =
            if (row.isNull("partitions_count")) 0L
            else row.getLong("partitions_count")
          total += mean * count
        }
        Option.when(total > 0)(total)
      } catch {
        case _: Throwable => None
      }
    }

  private def autoTuneSource(spark: SparkSession,
                             source: SourceSettings.Cassandra,
                             targetFileSizeMB: Option[Int]): AutoTuning = {
    val connector =
      Connectors.sourceConnector(spark.sparkContext.getConf, source)
    val nodeCount = connector.withSessionDo(_.getMetadata.getNodes.size)
    val localShards = queryLocalShardCount(connector)
    val totalShards = localShards.map(_ * math.max(1, nodeCount))
    val estimatedTableBytes = queryEstimatedTableBytes(connector, source)
    val targetBytes =
      targetFileSizeMB.filter(_ > 0).map(_.toLong * 1024L * 1024L)
    val sizeBasedSplits =
      for {
        bytes <- estimatedTableBytes
        perFile <- targetBytes
      } yield math.max(1, math.ceil(bytes.toDouble / perFile.toDouble).toInt)

    val tunedConnections = source.connections.orElse(
      localShards.map(shards =>
        math.max(1, math.min(8, math.ceil(shards.toDouble / 4.0).toInt)))
    )
    val tunedSplitCount =
      source.splitCount.orElse((sizeBasedSplits, totalShards) match {
        case (Some(bySize), Some(byShards)) => Some(math.max(bySize, byShards))
        case (Some(bySize), None)           => Some(bySize)
        case (None, Some(byShards))         => Some(byShards)
        case _                              => None
      })

    val tunedSource =
      source.copy(splitCount = tunedSplitCount, connections = tunedConnections)

    log.info(
      s"CQL source auto-tuning: localShards=${localShards.getOrElse("unknown")}, nodeCount=$nodeCount, " +
        s"estimatedTableBytes=${estimatedTableBytes.getOrElse("unknown")}, " +
        s"splitCount=${tunedSource.splitCount.getOrElse("default")}, " +
        s"connections=${tunedSource.connections.getOrElse("default")}")

    AutoTuning(localShards, nodeCount, estimatedTableBytes, tunedSource)
  }

  def readDataframe(spark: SparkSession,
                    source: SourceSettings.Cassandra,
                    preserveTimes: Boolean,
                    tokenRangesToSkip: Set[(Token[_], Token[_])],
                    targetFileSizeMB: Option[Int] = None): SourceDataFrame = {
    val tuning = autoTuneSource(spark, source, targetFileSizeMB)
    val tunedSource = tuning.tunedSource
    val connector =
      Connectors.sourceConnector(spark.sparkContext.getConf, tunedSource)
    val consistencyLevel = source.consistencyLevel match {
      case "LOCAL_QUORUM" => ConsistencyLevel.LOCAL_QUORUM
      case "QUORUM"       => ConsistencyLevel.QUORUM
      case "LOCAL_ONE"    => ConsistencyLevel.LOCAL_ONE
      case "ONE"          => ConsistencyLevel.ONE
      case _              => ConsistencyLevel.LOCAL_QUORUM
    }
    if (consistencyLevel.toString == source.consistencyLevel) {
      log.info(
        s"Using consistencyLevel [${consistencyLevel}] for SOURCE based on source config [${source.consistencyLevel}]")
    } else {
      log.info(
        s"Using DEFAULT consistencyLevel [${consistencyLevel}] for SOURCE based on unrecognized source config [${source.consistencyLevel}]")
    }

    val readConf = ReadConf
      .fromSparkConf(spark.sparkContext.getConf)
      .copy(
        splitCount = tunedSource.splitCount,
        fetchSizeInRows = tunedSource.fetchSize,
        consistencyLevel = consistencyLevel
      )

    val tableDef =
      connector.withSessionDo(
        Schema.tableFromCassandra(_, tunedSource.keyspace, tunedSource.table))
    log.info("TableDef retrieved for source:")
    log.info(tableDef)

    val origSchema = StructType(
      tableDef.columns.map(DataTypeConverter.toStructField))
    log.info("Original schema loaded:")
    origSchema.printTreeString()

    val selection = createSelection(tableDef, origSchema, preserveTimes)
      .fold(throw _, identity)

    val selectCassandraRDD = spark.sparkContext
      .cassandraTable[CassandraSQLRow](
        tunedSource.keyspace,
        tunedSource.table,
        (s, e) => !tokenRangesToSkip.contains((s, e)))
      .withConnector(connector)
      .withReadConf(readConf)
      .select(selection.columnRefs: _*)

    val finalCassandraRDD = tunedSource.where match {
      case Some(filter) => selectCassandraRDD.where(filter)
      case None         => selectCassandraRDD
    }

    val rdd = finalCassandraRDD
      .asInstanceOf[RDD[Row]]
      .map { row =>
        // We need to handle three conversions here that are not done for us:
        // - UTF8Strings to plain Strings
        // - UDTValue to Row
        // - TupleValue to Row
        //
        // We're using the RDD API of the Cassandra connector, and these conversions are
        // done in the SourceRelation connector of the Dataframe API. So we have to replicate
        // them here. Future versions of the migrator will use the DataFrame API directly to
        // avoid this replication.
        lazy val convertRowTypes: Any => Any = {
          case x: UTF8String => x.toString
          case set: Set[_]   => set.map(convertRowTypes)
          case list: List[_] => list.map(convertRowTypes)
          case map: Map[_, _] =>
            map.map {
              case (k, v) => convertRowTypes(k) -> convertRowTypes(v)
            }
          case ab: ArrayBuffer[_] => ab.map(convertRowTypes)
          case udt: UDTValue =>
            Row.fromSeq(udt.columnValues.map(convertRowTypes))
          case tuple: TupleValue =>
            Row.fromSeq(tuple.values.map(convertRowTypes))
          case x => x
        }

        Row.fromSeq(row.toSeq.map(convertRowTypes))
      }

    val resultingDataframe = adjustDataframeForTimestampPreservation(
      spark,
      spark.createDataFrame(rdd, selection.schema),
      selection.timestampColumns,
      origSchema,
      tableDef
    )

    SourceDataFrame(resultingDataframe, selection.timestampColumns, true)
  }
}

package com.scylladb.migrator.config

import cats.implicits._
import com.datastax.spark.connector.rdd.partitioner.dht.{ BigIntToken, LongToken, Token }
import io.circe.generic.semiauto.{ deriveDecoder, deriveEncoder }
import io.circe.syntax._
import io.circe.yaml.parser
import io.circe.yaml.syntax._
import io.circe.{ Decoder, DecodingFailure, Encoder, Error, Json }

case class MigratorConfig(source: SourceSettings,
                          target: TargetSettings,
                          renames: Option[List[Rename]],
                          savepoints: Savepoints,
                          skipTokenRanges: Option[Set[(Token[_], Token[_])]],
                          skipSegments: Option[Set[Int]],
                          skipParquetFiles: Option[Set[String]],
                          validation: Option[Validation]) {
  def render: String = this.asJson.asYaml.spaces2

  def getRenamesOrNil: List[Rename] = renames.getOrElse(Nil)

  /** The list of renames modelled as a Map from the old column name to the new column name */
  lazy val renamesMap: Map[String, String] =
    getRenamesOrNil.map(rename => rename.from -> rename.to).toMap.withDefault(identity)

  def getSkipTokenRangesOrEmptySet: Set[(Token[_], Token[_])] = skipTokenRanges.getOrElse(Set.empty)

  def getSkipParquetFilesOrEmptySet: Set[String] = skipParquetFiles.getOrElse(Set.empty)

}
object MigratorConfig {
  implicit val tokenEncoder: Encoder[Token[_]] = Encoder.instance {
    case LongToken(value)   => Json.obj("type" := "long", "value"   := value)
    case BigIntToken(value) => Json.obj("type" := "bigint", "value" := value)
  }

  implicit val tokenDecoder: Decoder[Token[_]] = Decoder.instance { cursor =>
    for {
      tpe <- cursor.get[String]("type")
      result <- tpe match {
                 case "long"    => cursor.get[Long]("value").map(LongToken(_))
                 case "bigint"  => cursor.get[BigInt]("value").map(BigIntToken(_))
                 case otherwise => Left(DecodingFailure(s"Unknown token type '$otherwise'", Nil))
               }
    } yield result
  }

  implicit val migratorConfigDecoder: Decoder[MigratorConfig] = deriveDecoder[MigratorConfig]
  implicit val migratorConfigEncoder: Encoder[MigratorConfig] = deriveEncoder[MigratorConfig]

  def loadFrom(path: String): MigratorConfig = {
    loadFromPath(path).fold(
      err => throw new IllegalArgumentException(err),
      identity
    )
  }

  /** Load and validate config, returning Either[errorMessage, MigratorConfig].
    * Use this for validation without throwing.
    */
  def loadFromPath(path: String): Either[String, MigratorConfig] = {
    val file = new java.io.File(path)
    if (!file.exists()) {
      return Left(s"Config file not found: $path")
    }
    if (!file.canRead()) {
      return Left(s"Config file not readable: $path")
    }

    val configData = try {
      scala.io.Source.fromFile(file).getLines().mkString("\n")
    } catch {
      case e: Exception =>
        return Left(s"Failed to read config file: ${e.getMessage}")
    }

    val trimmed = configData.trim
    if (trimmed.isEmpty) {
      return Left("Config file is empty")
    }

    parser
      .parse(trimmed)
      .leftWiden[Error]
      .flatMap(_.as[MigratorConfig])
      .leftMap {
        case df: DecodingFailure =>
          val pathStr = df.history.map(_.toString).mkString(".")
          val hint = if (pathStr.contains("target") || pathStr.contains("source")) {
            " Check that 'source' and 'target' sections have correct indentation (2 spaces per level) and required fields."
          } else ""
          s"Invalid config at $pathStr: ${df.message}.$hint"
        case pf: io.circe.ParsingFailure =>
          s"YAML parse error: ${pf.message}. Check indentation (use spaces, not tabs) and YAML syntax."
        case other =>
          s"Config error: $other"
      }
  }
}

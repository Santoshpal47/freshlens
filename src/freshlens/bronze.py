"""Bronze: raw JSON pages → one Delta table of string-typed rows plus lineage columns.

No cleaning happens here. Bronze answers "what exactly did the source send us, and when?"
Loads are idempotent: each (source, batch) slice is replaced as a whole with ``replaceWhere``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from freshlens.config import Settings

log = logging.getLogger(__name__)

BUSINESS_COLS = [
    "state",
    "district",
    "market",
    "commodity",
    "variety",
    "grade",
    "arrival_date",
    "min_price",
    "max_price",
    "modal_price",
]
LINEAGE_COLS = ["_source", "_batch", "_source_file", "_fetched_at", "_ingested_at"]
BRONZE_COLS = BUSINESS_COLS + LINEAGE_COLS


def read_raw_pages(spark: SparkSession, folder: str | Path, source: str, batch: str) -> DataFrame | None:
    """Read every ``page_*.json[.gz]`` under ``folder`` and flatten the ``records`` array."""
    folder = Path(folder)
    if not any(folder.rglob("page_*.json*")):
        log.warning("no raw pages under %s", folder)
        return None

    pages = (
        spark.read.option("multiLine", True)
        .option("recursiveFileLookup", True)  # don't treat key=value dirs as partitions
        .option("pathGlobFilter", "page_*.json*")  # plain or gzip
        .json(str(folder))
        .select("*", F.col("_metadata.file_path").alias("_source_file"))
    )
    if "records" not in pages.columns or not str(pages.schema["records"].dataType).startswith("ArrayType(StructType"):
        log.warning("raw pages under %s contain no records", folder)
        return None

    rows = pages.select(
        F.explode("records").alias("r"),
        "_source_file",
        F.to_timestamp("fetched_at").alias("_fetched_at"),
    ).select("r.*", "_source_file", "_fetched_at")

    # The daily resource uses snake_case keys and numbers; the history resource uses
    # Title_Case keys and strings. Bronze lower-cases names and keeps every value as a string.
    rows = rows.toDF(*[c.lower() for c in rows.columns])
    for col in BUSINESS_COLS:
        rows = rows.withColumn(col, F.col(col).cast("string") if col in rows.columns else F.lit(None).cast("string"))

    return rows.select(
        *BUSINESS_COLS,
        F.lit(source).alias("_source"),
        F.lit(batch).alias("_batch"),
        "_source_file",
        "_fetched_at",
        F.current_timestamp().alias("_ingested_at"),
    )


def write_bronze(settings: Settings, df: DataFrame, source: str, batch: str) -> int:
    df = df.select(*BRONZE_COLS)
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"_source = '{source}' AND _batch = '{batch}'")
        .save(settings.table("bronze", "prices"))
    )
    n = (
        df.sparkSession.read.format("delta")
        .load(settings.table("bronze", "prices"))
        .where((F.col("_source") == source) & (F.col("_batch") == batch))
        .count()
    )
    log.info("bronze %s/%s: %d rows", source, batch, n)
    return n

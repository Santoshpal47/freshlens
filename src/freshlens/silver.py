"""Silver: typed, cleaned, de-duplicated prices — one row per mandi × commodity × variety × grade × day.

* Text is trimmed and whitespace-collapsed, market suffixes (" APMC") are stripped and alias maps
  are applied, so the history feed's "Azadpur" and the daily feed's "Azadpur APMC" become one mandi.
* Prices go from ₹/quintal to ₹/kg as well (1 quintal = 100 kg). A min/max of 0 means "not reported"
  and becomes null.
* Rows that break row-level rules go to a quarantine table with a reason. They are never dropped
  silently.
* Upserts use a Delta MERGE on the natural key, so re-runs and late corrections are safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from freshlens.config import Settings

log = logging.getLogger(__name__)

NATURAL_KEY = ["state", "district", "market", "commodity", "variety", "grade", "arrival_date"]
PRICE_COLS = ["min_price", "max_price", "modal_price"]


def _clean_text(col: Column) -> Column:
    cleaned = F.regexp_replace(F.trim(col), r"\s+", " ")
    return F.when(cleaned == "", None).otherwise(cleaned)


def _apply_aliases(col: Column, mapping: dict[str, str]) -> Column:
    if not mapping:
        return col
    pairs = [x for k, v in mapping.items() for x in (F.lit(k.strip().lower()), F.lit(v))]
    return F.coalesce(F.try_element_at(F.create_map(*pairs), F.lower(col)), col)


def _parse_date(col: Column) -> Column:
    return F.coalesce(
        *[F.try_to_timestamp(col, F.lit(fmt)).cast("date") for fmt in ("dd/MM/yyyy", "yyyy-MM-dd", "dd-MM-yyyy")]
    )


def _parse_price(col: Column) -> Column:
    return F.regexp_replace(col, ",", "").try_cast("double")


def clean(bronze: DataFrame, settings: Settings) -> DataFrame:
    """Type and standardise bronze rows; adds ``dq_reason`` (null = row is valid)."""
    aliases = settings.aliases
    df = bronze
    for c in ["state", "district", "market", "commodity", "variety", "grade"]:
        df = df.withColumn(c, _clean_text(F.col(c)))

    df = (
        df.withColumn("market_raw", F.col("market"))
        .withColumn("market", F.regexp_replace("market", r"(?i)\s+(APMC|\(F&V\))$", ""))
        .withColumn("market", _apply_aliases(F.col("market"), aliases.get("market", {})))
        .withColumn("commodity", _apply_aliases(F.col("commodity"), aliases.get("commodity", {})))
        .withColumn("arrival_date", _parse_date(F.col("arrival_date")))
    )
    for c in PRICE_COLS:
        df = df.withColumn(c, _parse_price(F.col(c)))
    # Some mandis report min/max as 0 when they only record a modal price: that means "not reported".
    for c in ["min_price", "max_price"]:
        df = df.withColumn(c, F.when(F.col(c) > 0, F.col(c)))
    df = df.withColumn("modal_price_kg", F.round(F.col("modal_price") / 100, 2))

    max_kg = float(settings.quality["max_price_per_kg"])
    reason = (
        F.when(F.col("state").isNull() | F.col("market").isNull() | F.col("commodity").isNull(), "missing_key")
        .when(F.col("arrival_date").isNull(), "bad_date")
        .when(F.col("modal_price").isNull() | (F.col("modal_price") <= 0), "bad_modal_price")
        .when(F.col("min_price") > F.col("modal_price"), "min_above_modal")
        .when(F.col("modal_price") > F.col("max_price"), "modal_above_max")
        .when(F.col("modal_price_kg") > max_kg, "implausible_price")
    )
    return df.withColumn("dq_reason", reason)


def dedupe_latest(df: DataFrame) -> DataFrame:
    """Keep the most recently fetched version of each natural key."""
    w = Window.partitionBy(*NATURAL_KEY).orderBy(F.col("_fetched_at").desc_nulls_last(), F.col("_ingested_at").desc())
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


@dataclass
class SilverResult:
    inserted: int
    updated: int
    quarantined: int
    min_date: date | None
    max_date: date | None


def _silver_select(df: DataFrame) -> DataFrame:
    return df.select(
        *NATURAL_KEY,
        *PRICE_COLS,
        "modal_price_kg",
        "market_raw",
        "_source",
        "_batch",
        "_fetched_at",
        F.sha2(F.concat_ws("|", *[F.col(c).cast("string") for c in PRICE_COLS]), 256).alias("record_hash"),
        F.current_timestamp().alias("_updated_at"),
    )


def upsert_silver(spark: SparkSession, settings: Settings, source: str, batch: str) -> SilverResult:
    bronze = (
        spark.read.format("delta")
        .load(settings.table("bronze", "prices"))
        .where((F.col("_source") == source) & (F.col("_batch") == batch))
    )
    cleaned = clean(bronze, settings).cache()

    # 1) quarantine — replaced per batch so re-runs don't duplicate
    bad = cleaned.where(F.col("dq_reason").isNotNull()).select(
        "dq_reason", *NATURAL_KEY, *PRICE_COLS, "market_raw", "_source", "_batch", "_source_file", "_ingested_at"
    )
    (
        bad.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"_source = '{source}' AND _batch = '{batch}'")
        .save(settings.table("silver", "quarantine"))
    )
    n_bad = bad.count()

    # 2) MERGE valid, de-duplicated rows into silver.prices
    # The daily API's commodity filter is a loose text match ("Green Chilli" also returns "Green Peas",
    # "Banana - Green", ...). Raw keeps what was sent; silver keeps only the configured commodities.
    in_scope = F.lower("commodity").isin([c.lower() for c in settings.commodities])
    out_of_scope = cleaned.where(F.col("dq_reason").isNull() & ~in_scope).count()
    if out_of_scope:
        log.info("silver %s/%s: dropped %d out-of-scope rows (commodity not configured)", source, batch, out_of_scope)
    good = _silver_select(dedupe_latest(cleaned.where(F.col("dq_reason").isNull() & in_scope)))
    path = settings.table("silver", "prices")
    if not DeltaTable.isDeltaTable(spark, path):
        good.limit(0).write.format("delta").partitionBy("commodity").save(path)

    target = DeltaTable.forPath(spark, path)
    on = " AND ".join(f"t.{k} <=> s.{k}" for k in NATURAL_KEY)
    (
        target.alias("t")
        .merge(good.alias("s"), on)
        # only overwrite when the numbers changed AND the incoming copy is not older
        .whenMatchedUpdateAll(condition="t.record_hash <> s.record_hash AND s._fetched_at >= t._fetched_at")
        .whenNotMatchedInsertAll()
        .execute()
    )
    metrics = target.history(1).select("operationMetrics").first()[0] or {}
    span = good.agg(F.min("arrival_date"), F.max("arrival_date")).first()
    cleaned.unpersist()

    result = SilverResult(
        inserted=int(metrics.get("numTargetRowsInserted", 0)),
        updated=int(metrics.get("numTargetRowsUpdated", 0)),
        quarantined=n_bad,
        min_date=span[0],
        max_date=span[1],
    )
    log.info("silver %s/%s: %s", source, batch, result)
    return result

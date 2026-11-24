"""Gold: star schema for BI — dim_date, dim_mandi, dim_commodity and fact_price_daily.

Surrogate keys come from ``xxhash64`` of the natural attributes. That makes them deterministic,
so facts and dims can be rebuilt independently and still join.
"""

from __future__ import annotations

import csv
import logging
from datetime import date

import h3
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

from freshlens.config import Settings

log = logging.getLogger(__name__)
H3_RESOLUTION = 7  # ~5 km² cells: enough to place a mandi relative to a dark-store cluster


def mandi_key(state: str = "state", district: str = "district", market: str = "market"):
    return F.xxhash64(F.lower(state), F.lower(district), F.lower(market))


def commodity_key(commodity: str = "commodity"):
    return F.xxhash64(F.lower(commodity))


def _overwrite(df: DataFrame, path: str) -> None:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", True).save(path)


def load_geo_seed(spark: SparkSession, settings: Settings) -> DataFrame:
    rows = []
    with open(settings.geo_seed) as fh:
        for r in csv.DictReader(fh):
            lat, lon = float(r["lat"]), float(r["lon"])
            rows.append((r["state"], r["market"], lat, lon, r["role"], h3.latlng_to_cell(lat, lon, H3_RESOLUTION)))
    schema = StructType(
        [
            StructField("seed_state", StringType()),
            StructField("seed_market", StringType()),
            StructField("lat", DoubleType()),
            StructField("lon", DoubleType()),
            StructField("role", StringType()),
            StructField("h3_r7", StringType()),
        ]
    )
    return spark.createDataFrame(rows, schema)


def build_dims(spark: SparkSession, settings: Settings) -> None:
    silver = spark.read.format("delta").load(settings.table("silver", "prices"))

    seed = load_geo_seed(spark, settings)
    mandis = silver.select("state", "district", "market").distinct()
    dim_mandi = mandis.join(
        seed,
        (F.lower(mandis.state) == F.lower(seed.seed_state)) & (F.lower(mandis.market) == F.lower(seed.seed_market)),
        "left",
    ).select(
        mandi_key().alias("mandi_key"),
        "state",
        "district",
        "market",
        "lat",
        "lon",
        "h3_r7",
        F.coalesce("role", F.when(F.col("state") == settings.home_state, "destination").otherwise("other")).alias(
            "role"
        ),
    )
    _overwrite(dim_mandi, settings.table("gold", "dim_mandi"))

    categories = F.create_map(*[x for k, v in settings.commodities.items() for x in (F.lit(k.lower()), F.lit(v))])
    names = F.create_map(*[x for k, v in settings.display_names.items() for x in (F.lit(k.lower()), F.lit(v))])
    dim_commodity = (
        silver.select("commodity")
        .distinct()
        .select(
            commodity_key().alias("commodity_key"),
            "commodity",
            F.coalesce(F.try_element_at(names, F.lower("commodity")), F.col("commodity")).alias("display_name"),
            F.coalesce(F.try_element_at(categories, F.lower("commodity")), F.lit("other")).alias("category"),
        )
    )
    _overwrite(dim_commodity, settings.table("gold", "dim_commodity"))

    lo, hi = silver.agg(F.min("arrival_date"), F.max("arrival_date")).first()
    if lo is None:
        return
    dim_date = (
        spark.range(1)
        .select(F.explode(F.sequence(F.lit(lo), F.lit(hi))).alias("date"))
        .select(
            F.date_format("date", "yyyyMMdd").cast("int").alias("date_key"),
            "date",
            F.year("date").alias("year"),
            F.month("date").alias("month"),
            F.date_format("date", "MMM").alias("month_name"),
            F.weekofyear("date").alias("week_of_year"),
            F.date_format("date", "EEE").alias("day_name"),
            F.dayofweek("date").isin(1, 7).alias("is_weekend"),
        )
    )
    _overwrite(dim_date, settings.table("gold", "dim_date"))


def upsert_fact(spark: SparkSession, settings: Settings, start: date, end: date) -> int:
    """Rebuild fact rows for [start, end] only — incremental and idempotent via replaceWhere."""
    silver = (
        spark.read.format("delta")
        .load(settings.table("silver", "prices"))
        .where(F.col("arrival_date").between(F.lit(start), F.lit(end)))
    )
    fact = silver.select(
        F.date_format("arrival_date", "yyyyMMdd").cast("int").alias("date_key"),
        F.col("arrival_date").alias("date"),
        mandi_key().alias("mandi_key"),
        commodity_key().alias("commodity_key"),
        "variety",
        "grade",
        F.col("min_price").alias("min_price_qtl"),
        F.col("max_price").alias("max_price_qtl"),
        F.col("modal_price").alias("modal_price_qtl"),
        "modal_price_kg",
        F.col("_source").alias("source"),
    )
    (
        fact.write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", f"date >= '{start}' AND date <= '{end}'")
        .save(settings.table("gold", "fact_price_daily"))
    )
    n = fact.count()
    log.info("fact_price_daily %s..%s: %d rows", start, end, n)
    return n

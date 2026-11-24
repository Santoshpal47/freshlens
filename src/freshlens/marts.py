"""Analytical marts on top of the star schema.

mart_mandi_daily      one price per mandi × commodity × day (median across varieties/grades)
mart_city_daily       one price per city × commodity × day (median across the city's markets)
mart_city_volatility  volatility on the city series
mart_volatility       day-on-day log returns, rolling volatility and coefficient of variation
mart_sourcing_spread  Delhi price vs (source-mandi price + freight) for each configured lane
mart_lead_lag         correlation of Delhi returns with source returns shifted by 0..N days
mart_lead_lag_weekly  the same on weekly medians (less day-to-day reporting noise)
mart_alert_backtest   weekly rule: source up >=X% this week → Delhi up next week? (vs. the base rate)
mart_alerts           this week's signal per lane
"""

from __future__ import annotations

import logging
import math

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from freshlens.config import Settings

log = logging.getLogger(__name__)


def _read(spark: SparkSession, settings: Settings, layer: str, name: str) -> DataFrame:
    return spark.read.format("delta").load(settings.table(layer, name))


def _write(df: DataFrame, settings: Settings, name: str) -> None:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", True).save(settings.table("gold", name))


def _day(col: str = "date"):
    """Days since epoch: lets window frames be defined in calendar days, not rows."""
    return F.datediff(F.col(col), F.lit("1970-01-01"))


# ----------------------------------------------------------------------------------------------
def mandi_daily(spark: SparkSession, settings: Settings) -> DataFrame:
    fact = _read(spark, settings, "gold", "fact_price_daily")
    mandi = _read(spark, settings, "gold", "dim_mandi")
    com = _read(spark, settings, "gold", "dim_commodity")
    return (
        fact.groupBy("date", "mandi_key", "commodity_key")
        .agg(
            F.percentile_approx("modal_price_kg", 0.5).alias("modal_price_kg"),
            F.min(F.col("min_price_qtl") / 100).alias("min_price_kg"),
            F.max(F.col("max_price_qtl") / 100).alias("max_price_kg"),
            F.count("*").alias("n_quotes"),
        )
        .join(mandi.select("mandi_key", "state", "market", "city", "role"), "mandi_key")
        .join(com.select("commodity_key", "commodity", "display_name", "category"), "commodity_key")
    )


def city_daily(daily: DataFrame) -> DataFrame:
    """One price per city × item × day: median across the city's markets that reported that day."""
    return (
        daily.where(F.col("city").isNotNull())
        .groupBy("date", "city", "commodity_key", "commodity", "display_name", "category")
        .agg(
            F.percentile_approx("modal_price_kg", 0.5).alias("modal_price_kg"),
            F.countDistinct("market").alias("n_markets"),
        )
    )


def volatility(
    daily: DataFrame, settings: Settings, keys: tuple[str, ...] = ("mandi_key", "commodity_key")
) -> DataFrame:
    a = settings.analysis
    series = Window.partitionBy(*keys).orderBy("date")
    df = (
        daily.withColumn("day", _day())
        .withColumn("prev_price", F.lag("modal_price_kg").over(series))
        .withColumn("gap_days", F.col("day") - F.lag("day").over(series))
        .withColumn(
            "log_return",
            F.when(
                (F.col("gap_days") <= a["max_return_gap_days"]) & (F.col("prev_price") > 0),
                F.log(F.col("modal_price_kg") / F.col("prev_price")),
            ),
        )
    )
    for n in a["volatility_windows"]:
        w = Window.partitionBy(*keys).orderBy("day").rangeBetween(-(n - 1), 0)
        df = (
            df.withColumn(f"vol_{n}d_pct", F.round(F.stddev("log_return").over(w) * 100, 2))
            .withColumn(
                f"cv_{n}d_pct", F.round(F.stddev("modal_price_kg").over(w) / F.avg("modal_price_kg").over(w) * 100, 2)
            )
            .withColumn(f"obs_{n}d", F.count("log_return").over(w))
        )
    return df.drop("prev_price")


def _lane_frame(spark: SparkSession, settings: Settings) -> DataFrame:
    rows = [
        (
            f"{ln['commodity']}: {ln['source']} → {ln['city']}",
            ln["commodity"],
            ln["source"],
            ln["city"],
            float(ln["freight_per_kg"]),
        )
        for ln in settings.lanes
    ]
    return spark.createDataFrame(
        rows, "lane string, commodity string, source string, destination string, freight_per_kg double"
    )


def _lane_side(vol: DataFrame, lanes: DataFrame, side: str) -> DataFrame:
    """Price/return series of one end of each lane (side = 'source' | 'destination')."""
    v = vol.alias("v")
    joined = v.join(
        lanes.alias("l"),
        (F.lower(F.col("v.commodity")) == F.lower(F.col("l.commodity")))
        & (F.lower(F.col("v.market")) == F.lower(F.col(f"l.{side}"))),
    )
    p = "src" if side == "source" else "dst"
    return joined.select(
        F.col("l.lane").alias("lane"),
        F.col("v.date").alias("date"),
        F.col("v.day").alias("day"),
        F.col("v.modal_price_kg").alias(f"{p}_price_kg"),
        F.col("v.log_return").alias(f"{p}_return"),
        F.col("l.freight_per_kg").alias("freight_per_kg"),
    )


def sourcing_spread(src: DataFrame, dst: DataFrame) -> DataFrame:
    return (
        dst.join(src.drop("freight_per_kg"), ["lane", "date", "day"])
        .withColumn("landed_cost_kg", F.round(F.col("src_price_kg") + F.col("freight_per_kg"), 2))
        .withColumn("spread_kg", F.round(F.col("dst_price_kg") - F.col("landed_cost_kg"), 2))
        .withColumn("direct_sourcing_cheaper", F.col("spread_kg") > 0)
        .select(
            "lane",
            "date",
            "src_price_kg",
            "freight_per_kg",
            "landed_cost_kg",
            "dst_price_kg",
            "spread_kg",
            "direct_sourcing_cheaper",
        )
    )


def lead_lag(
    spark: SparkSession,
    src: DataFrame,
    dst: DataFrame,
    settings: Settings,
    max_lag: int | None = None,
    min_overlap: int | None = None,
) -> DataFrame:
    """corr(dst_return[t], src_return[t - lag]) for lag = 0..max_lag, per lane.

    ``day`` is the time index: calendar days for the daily view, week numbers for the weekly view.
    A lag counts as the lane's lead only if it has enough paired periods AND the correlation
    clears ``min_corr``. Otherwise the honest answer is "no lead detected".
    """
    a = settings.analysis
    max_lag = a["max_lag_days"] if max_lag is None else max_lag
    min_overlap = a["min_overlap_days"] if min_overlap is None else min_overlap
    lags = spark.range(0, max_lag + 1).withColumnRenamed("id", "lag_days")
    shifted = (
        src.where(F.col("src_return").isNotNull())
        .crossJoin(lags)
        .withColumn("day", F.col("day") + F.col("lag_days"))
        .select("lane", "day", "lag_days", "src_return")
    )
    pairs = shifted.join(
        dst.where(F.col("dst_return").isNotNull()).select("lane", "day", "dst_return"), ["lane", "day"]
    )
    stats = pairs.groupBy("lane", "lag_days").agg(
        F.round(F.corr("src_return", "dst_return"), 3).alias("corr"),
        F.count("*").alias("n_days"),
    )
    reliable = (F.col("n_days") >= min_overlap) & (F.col("corr") >= a["min_corr"])
    best = Window.partitionBy("lane").orderBy(F.when(reliable, F.col("corr")).desc_nulls_last())
    return stats.withColumn("reliable", reliable).withColumn("is_best_lag", (F.row_number().over(best) == 1) & reliable)


def to_weekly(side: DataFrame, prefix: str) -> DataFrame:
    """Weekly median price per lane end, with week-on-week log returns (consecutive weeks only).

    Daily mandi quotes are noisy (arrival mix, quality grade, missing days). Weekly medians
    keep the trend and drop most of that noise.
    """
    price = f"{prefix}_price_kg"
    weekly = (
        side.withColumn("week", F.date_trunc("week", "date").cast("date"))
        .groupBy("lane", "week")
        .agg(F.percentile_approx(price, 0.5).alias(price))
        .withColumn("day", F.floor(F.datediff("week", F.lit("1970-01-05")) / 7).cast("int"))
    )
    order = Window.partitionBy("lane").orderBy("day")
    return weekly.withColumn(
        f"{prefix}_return",
        F.when(F.col("day") - F.lag("day").over(order) == 1, F.log(F.col(price) / F.lag(price).over(order))),
    ).withColumnRenamed("week", "date")


def lead_lag_weekly(spark: SparkSession, src: DataFrame, dst: DataFrame, settings: Settings) -> DataFrame:
    a = settings.analysis
    out = lead_lag(
        spark,
        to_weekly(src, "src"),
        to_weekly(dst, "dst"),
        settings,
        max_lag=a["weekly_max_lag_weeks"],
        min_overlap=a["weekly_min_overlap_weeks"],
    )
    return out.withColumnRenamed("lag_days", "lag_weeks").withColumnRenamed("n_days", "n_weeks")


def alert_backtest(src_w: DataFrame, dst_w: DataFrame, settings: Settings) -> tuple[DataFrame, DataFrame]:
    """Weekly spike rule: source mandi up >= threshold this week → is Delhi up NEXT week?

    Every spike episode is counted once (its first week). The hit rate only means something next to
    the base rate: how often Delhi rises in any week.
    """
    pct = float(settings.analysis["spike_threshold_pct"])
    thr = math.log(1 + pct / 100)
    order = Window.partitionBy("lane").orderBy("day")
    s = src_w.withColumn("_over", F.coalesce(F.col("src_return") >= thr, F.lit(False))).withColumn(
        "spike", F.col("_over") & ~F.coalesce(F.lag("_over").over(order), F.lit(False))
    )
    nxt = dst_w.select("lane", (F.col("day") - 1).alias("day"), F.col("dst_return").alias("dst_next"))
    ev = s.join(nxt, ["lane", "day"]).where(F.col("dst_next").isNotNull())
    up = (F.col("dst_next") > 0).cast("double")
    chg = (F.exp("dst_next") - 1) * 100
    backtest = ev.groupBy("lane").agg(
        F.sum(F.col("spike").cast("int")).alias("n_spikes"),
        F.round(F.avg(F.when(F.col("spike"), up)) * 100, 1).alias("hit_rate_pct"),
        F.round(F.avg(up) * 100, 1).alias("base_rate_up_pct"),
        F.round(F.avg(F.when(F.col("spike"), chg)), 2).alias("avg_delhi_next_week_after_spike_pct"),
        F.round(F.avg(chg), 2).alias("avg_delhi_next_week_all_pct"),
        F.count("*").alias("n_weeks_tested"),
    )

    latest = Window.partitionBy("lane").orderBy(F.col("day").desc())
    today = (
        s.withColumn("_rn", F.row_number().over(latest))
        .where("_rn = 1")
        .join(backtest.select("lane", "hit_rate_pct", "base_rate_up_pct", "n_spikes"), "lane", "left")
        .select(
            "lane",
            F.col("date").alias("week_of"),
            F.col("src_price_kg").alias("source_price_kg"),
            F.round((F.exp("src_return") - 1) * 100, 2).alias("source_week_change_pct"),
            F.col("_over").alias("alert"),
            F.when(
                F.col("_over"),
                F.format_string(
                    "Source up >=%.0f%% this week: Delhi rose the next week in %.0f%% of %d past spikes"
                    " (base rate %.0f%%)",
                    F.lit(pct),
                    "hit_rate_pct",
                    "n_spikes",
                    "base_rate_up_pct",
                ),
            )
            .otherwise("no spike")
            .alias("message"),
        )
    )
    return backtest, today


def build_marts(spark: SparkSession, settings: Settings) -> None:
    daily = mandi_daily(spark, settings)
    _write(daily, settings, "mart_mandi_daily")
    daily = _read(spark, settings, "gold", "mart_mandi_daily")

    _write(city_daily(daily), settings, "mart_city_daily")
    _write(volatility(daily, settings), settings, "mart_volatility")  # per market (lane sources)
    _write(
        volatility(_read(spark, settings, "gold", "mart_city_daily"), settings, ("city", "commodity_key")),
        settings,
        "mart_city_volatility",
    )
    vol = _read(spark, settings, "gold", "mart_volatility")
    city_vol = _read(spark, settings, "gold", "mart_city_volatility").withColumn("market", F.col("city"))

    # lanes: source = a market, destination = a city (city price = median of its markets)
    lanes = _lane_frame(spark, settings)
    src = _lane_side(vol, lanes, "source").cache()
    dst = _lane_side(city_vol, lanes, "destination").cache()

    _write(sourcing_spread(src, dst), settings, "mart_sourcing_spread")
    ll = lead_lag(spark, src, dst, settings)
    _write(ll, settings, "mart_lead_lag")
    _write(lead_lag_weekly(spark, src, dst, settings), settings, "mart_lead_lag_weekly")
    backtest, today = alert_backtest(to_weekly(src, "src"), to_weekly(dst, "dst"), settings)
    _write(backtest, settings, "mart_alert_backtest")
    _write(today, settings, "mart_alerts")
    src.unpersist()
    dst.unpersist()
    log.info("marts rebuilt")

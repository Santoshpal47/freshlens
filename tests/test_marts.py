"""The lead-lag search must recover a lag that is planted in synthetic data."""

import math
import random
from datetime import date, timedelta

from freshlens import marts


def _series(spark, lag=3, days=200, seed=7):
    rnd = random.Random(seed)
    shocks = [rnd.gauss(0, 0.05) for _ in range(days + lag)]
    src_p, dst_p, rows = 20.0, 30.0, []
    start = date(2025, 1, 1)
    for i in range(days):
        src_p *= math.exp(shocks[i + lag])
        dst_p *= math.exp(shocks[i] * 0.8 + rnd.gauss(0, 0.01))  # Delhi follows the source `lag` days later
        d = start + timedelta(days=i)
        rows.append(("L", d, i, src_p, dst_p))
    df = spark.createDataFrame(rows, "lane string, date date, day int, src double, dst double")
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    w = Window.partitionBy("lane").orderBy("day")
    df = df.withColumn("src_return", F.log(F.col("src") / F.lag("src").over(w))).withColumn(
        "dst_return", F.log(F.col("dst") / F.lag("dst").over(w))
    )
    src = df.select(
        "lane", "date", "day", F.col("src").alias("src_price_kg"), "src_return", F.lit(2.0).alias("freight_per_kg")
    )
    dst = df.select(
        "lane", "date", "day", F.col("dst").alias("dst_price_kg"), "dst_return", F.lit(2.0).alias("freight_per_kg")
    )
    return src, dst


def test_lead_lag_recovers_planted_lag(spark, settings):
    src, dst = _series(spark, lag=3)
    out = marts.lead_lag(spark, src, dst, settings)
    best = out.where("is_best_lag").collect()
    assert len(best) == 1 and best[0]["lag_days"] == 3 and best[0]["corr"] > 0.9


def test_no_lag_claimed_without_enough_overlap(spark, settings):
    src, dst = _series(spark, lag=3, days=30)  # below min_overlap_days
    assert marts.lead_lag(spark, src, dst, settings).where("is_best_lag").count() == 0


def test_spread_is_destination_minus_landed_cost(spark, settings):
    src, dst = _series(spark, days=5)
    r = marts.sourcing_spread(src, dst).orderBy("date").first()
    assert r["landed_cost_kg"] == round(r["src_price_kg"] + 2.0, 2)
    assert abs(r["spread_kg"] - (r["dst_price_kg"] - r["landed_cost_kg"])) < 0.011


def test_weekly_view_recovers_a_two_week_lag(spark, settings):
    src, dst = _series(spark, lag=14, days=900)
    out = marts.lead_lag_weekly(spark, src, dst, settings)
    best = out.where("is_best_lag").collect()
    assert len(best) == 1 and best[0]["lag_weeks"] == 2


def test_spike_rule_beats_base_rate_when_source_leads(spark, settings):
    src, dst = _series(spark, lag=7, days=1400)  # Delhi follows the source one week later
    backtest, today = marts.alert_backtest(marts.to_weekly(src, "src"), marts.to_weekly(dst, "dst"), settings)
    r = backtest.first()
    assert r["n_spikes"] > 5 and r["hit_rate_pct"] > r["base_rate_up_pct"] + 20
    assert today.count() == 1

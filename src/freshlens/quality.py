"""Data-quality checks. Each run appends its results to ``ops/dq_results``.

Severity ``critical`` stops the pipeline (raises DataQualityError) *after* the results are
recorded, so a failure always leaves evidence. Severity ``warn`` is reported and the run goes on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from freshlens.config import Settings
from freshlens.silver import NATURAL_KEY

log = logging.getLogger(__name__)


class DataQualityError(RuntimeError):
    pass


@dataclass
class Check:
    name: str
    severity: str  # critical | warn
    passed: bool
    observed: str
    expected: str
    details: str = ""


def run_checks(
    spark: SparkSession,
    settings: Settings,
    run_id: str,
    run_date: date,
    loaded_rows: int | None = None,
    quarantined: int | None = None,
) -> list[Check]:
    q = settings.quality
    silver = spark.read.format("delta").load(settings.table("silver", "prices"))
    checks: list[Check] = []

    if loaded_rows is not None:
        checks.append(
            Check(
                "load_not_empty",
                "critical",
                loaded_rows > 0,
                str(loaded_rows),
                "> 0",
                "the source returned no rows for this load",
            )
        )
        if loaded_rows:
            rate = (quarantined or 0) / loaded_rows
            checks.append(
                Check(
                    "quarantine_rate",
                    "warn",
                    rate <= q["max_quarantine_rate"],
                    f"{rate:.2%}",
                    f"<= {q['max_quarantine_rate']:.0%}",
                    "rows failing row-level rules",
                )
            )

    total = silver.count()
    distinct = silver.select(*NATURAL_KEY).distinct().count()
    checks.append(Check("natural_key_unique", "critical", total == distinct, f"{total - distinct} dupes", "0"))

    bad_order = silver.where(
        (F.col("min_price") > F.col("modal_price"))
        | (F.col("modal_price") > F.col("max_price"))
        | (F.col("modal_price") <= 0)
    ).count()
    checks.append(Check("price_order_min_le_modal_le_max", "critical", bad_order == 0, str(bad_order), "0"))

    latest = silver.agg(F.max("arrival_date")).first()[0]
    lag_days = (run_date - latest).days if latest else None
    checks.append(
        Check(
            "freshness",
            "warn",
            lag_days is not None and lag_days <= q["freshness_days"],
            f"latest arrival {latest} ({lag_days} days old)",
            f"<= {q['freshness_days']} days",
        )
    )

    # tracked lane ends that have gone quiet: source markets, and destination cities (any of its markets)
    city_of = settings.market_city()
    seen = (
        silver.groupBy(F.lower("market").alias("m"), F.lower("commodity").alias("c"))
        .agg(F.max("arrival_date").alias("last"))
        .collect()
    )
    last_seen: dict[tuple[str, str], date] = {}
    for r in seen:
        for key in ((r["m"], r["c"]), (city_of.get(r["m"], "").lower(), r["c"])):
            if key[0] and (key not in last_seen or r["last"] > last_seen[key]):
                last_seen[key] = r["last"]
    tracked = {(ln["source"].lower(), ln["commodity"].lower()) for ln in settings.lanes}
    tracked |= {(ln["city"].lower(), ln["commodity"].lower()) for ln in settings.lanes}
    quiet = []
    for key in sorted(tracked):
        seen_on = last_seen.get(key)
        if latest and (seen_on is None or (latest - seen_on).days > q["stopped_reporting_days"]):
            quiet.append(f"{key[0]}/{key[1]} last={seen_on}")
    checks.append(
        Check(
            "tracked_lanes_reporting",
            "warn",
            not quiet,
            f"{len(quiet)} silent",
            f"0 silent > {q['stopped_reporting_days']}d",
            "; ".join(quiet),
        )
    )

    missing = [c for c in settings.commodities if silver.where(F.lower("commodity") == c.lower()).limit(1).count() == 0]
    checks.append(Check("commodity_coverage", "warn", not missing, f"{len(missing)} missing", "0", ", ".join(missing)))

    _record(spark, settings, run_id, checks)
    for c in checks:
        (log.info if c.passed else log.warning)(
            "DQ %-34s %-8s %s observed=%s expected=%s %s",
            c.name,
            c.severity,
            "PASS" if c.passed else "FAIL",
            c.observed,
            c.expected,
            c.details,
        )
    failed = [c.name for c in checks if c.severity == "critical" and not c.passed]
    if failed:
        raise DataQualityError(f"critical data-quality checks failed: {failed}")
    return checks


def _record(spark: SparkSession, settings: Settings, run_id: str, checks: list[Check]) -> None:
    now = datetime.now()
    rows = [(run_id, now, c.name, c.severity, c.passed, c.observed, c.expected, c.details) for c in checks]
    df = spark.createDataFrame(
        rows,
        "run_id string, checked_at timestamp, check string, severity string, passed boolean, "
        "observed string, expected string, details string",
    )
    df.write.format("delta").mode("append").save(settings.table("ops", "dq_results"))

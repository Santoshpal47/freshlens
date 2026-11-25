"""Orchestration: raw → bronze → silver → gold → marts → data quality."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import date, datetime
from pathlib import Path

from pyspark.sql import SparkSession

from freshlens import bronze, gold, marts, quality, silver
from freshlens.config import Settings, api_key
from freshlens.ingest.api_client import DataGovClient
from freshlens.ingest.landing import history_scopes, land_daily, land_history

log = logging.getLogger(__name__)


def make_client(settings: Settings) -> DataGovClient:
    """API client. FRESHLENS_API_BASE + FRESHLENS_RELAY_KEY route requests through the India relay
    (relay/): api.data.gov.in only answers Indian IP addresses."""
    src = settings.source
    relay = os.environ.get("FRESHLENS_API_BASE", "").strip()
    headers = {"x-relay-key": os.environ["FRESHLENS_RELAY_KEY"]} if relay else None
    return DataGovClient(
        api_key=api_key(),
        base_url=relay or src["base_url"],
        headers=headers,
        page_size=src["page_size"],
        timeout_s=src["request_timeout_s"],
        max_retries=src["max_retries"],
    )


def _process_batch(spark: SparkSession, settings: Settings, folder: Path, source: str, batch: str | None):
    df = bronze.read_raw_pages(spark, folder, source, batch)
    if df is None:
        return 0, None
    n = bronze.write_bronze(settings, df, source, batch)
    return n, silver.upsert_silver(spark, settings, source, batch)


def _publish(spark: SparkSession, settings: Settings, results, run_id: str, run_date: date, loaded: int | None) -> None:
    spans = [r for r in results if r and r.min_date]
    if spans:
        gold.build_dims(spark, settings)
        gold.upsert_fact(spark, settings, min(r.min_date for r in spans), max(r.max_date for r in spans))
        marts.build_marts(spark, settings)
    quarantined = sum(r.quarantined for r in results if r)
    quality.run_checks(spark, settings, run_id, run_date, loaded_rows=loaded, quarantined=quarantined)


def run_daily(spark: SparkSession, settings: Settings, run_date: date, fetch: bool = True) -> None:
    run_id = f"daily-{datetime.now():%Y%m%dT%H%M%S}"
    day_dir = Path(settings.raw_root) / "daily" / f"ingest_date={run_date}"
    if fetch:
        land_daily(settings, make_client(settings), run_date)
    loaded, result = _process_batch(spark, settings, day_dir, "daily", str(run_date))
    _publish(spark, settings, [result], run_id, run_date, loaded)


def run_backfill(spark: SparkSession, settings: Settings, fetch: bool = True, workers: int = 3) -> None:
    """Land every history scope (resumable, parallel), then process all history in a single pass."""
    run_id = f"backfill-{datetime.now():%Y%m%dT%H%M%S}"
    if fetch:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = [pool.submit(land_history, settings, make_client(settings), f) for f in history_scopes(settings)]
            for job in jobs:
                job.result()
    loaded, result = _process_batch(spark, settings, Path(settings.raw_root) / "history", "history", None)
    _publish(spark, settings, [result], run_id, date.today(), loaded)


def rebuild(spark: SparkSession, settings: Settings) -> None:
    """Drop the lake and replay every raw file, history then daily in date order.

    Raw is the source of truth, so the lake can always be rebuilt from it.
    """
    lake = Path(settings.data_root) / "lake"
    if lake.exists():
        shutil.rmtree(lake)
    run_backfill(spark, settings, fetch=False)
    days = sorted((Path(settings.raw_root) / "daily").glob("ingest_date=*"))
    for d in days:
        run_daily(spark, settings, date.fromisoformat(d.name.split("=", 1)[1]), fetch=False)


def refresh_gold(spark: SparkSession, settings: Settings) -> None:
    from pyspark.sql import functions as F

    s = spark.read.format("delta").load(settings.table("silver", "prices"))
    lo, hi = s.agg(F.min("arrival_date"), F.max("arrival_date")).first()
    gold.build_dims(spark, settings)
    gold.upsert_fact(spark, settings, lo, hi)
    marts.build_marts(spark, settings)

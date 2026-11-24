"""Export a slim, read-only snapshot of the gold marts for the hosted dashboard.

The hosted app (Streamlit Community Cloud) has no Spark and no Delta lake, just these small parquet
files, rebuilt every night by the GitHub Action and shipped on the ``deploy`` branch.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from freshlens.config import PROJECT_ROOT, Settings

log = logging.getLogger(__name__)
DEFAULT_OUT = PROJECT_ROOT / "dashboard" / "snapshot"


def export_snapshot(spark: SparkSession, settings: Settings, out: Path | None = None) -> Path:
    out = Path(out or DEFAULT_OUT)
    hub = settings.cfg.get("history", {}).get("hub_market", "Azadpur")

    def gold(name: str):
        return spark.read.format("delta").load(settings.table("gold", name))

    tables = {
        # only the columns the dashboard reads, so the snapshot stays a few MB
        "mart_mandi_daily": gold("mart_mandi_daily").select("date", "market", "commodity", "modal_price_kg"),
        "mart_volatility": gold("mart_volatility")
        .where(F.col("market") == hub)
        .select("date", "market", "commodity", "log_return", "vol_30d_pct", "obs_30d"),
        "mart_sourcing_spread": gold("mart_sourcing_spread"),
        "mart_lead_lag": gold("mart_lead_lag"),
        "mart_lead_lag_weekly": gold("mart_lead_lag_weekly"),
        "mart_alert_backtest": gold("mart_alert_backtest"),
        "mart_alerts": gold("mart_alerts"),
    }
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, df in tables.items():
        target = out / f"{name}.parquet"
        df.toPandas().to_parquet(target, index=False, compression="zstd")
        log.info("snapshot %s: %d rows, %.0f KB", name, df.count(), target.stat().st_size / 1024)
    return out

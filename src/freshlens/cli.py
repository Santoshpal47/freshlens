"""Command line: ``fpr daily | backfill | rebuild | gold | dq | show``."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime

from freshlens.config import load_settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="freshlens", description="FreshLens pipeline")
    p.add_argument("--data-root", help="lake/raw root (default ./data or $FPR_DATA_ROOT)")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("daily", help="fetch today's prices and run every layer")
    d.add_argument("--date", type=date.fromisoformat, default=date.today())
    d.add_argument("--no-fetch", action="store_true", help="reprocess raw already on disk")
    d.add_argument("--land-only", action="store_true", help="only snapshot today's API pages to raw (no Spark)")

    b = sub.add_parser("backfill", help="download history (resumable) and run every layer")
    b.add_argument("--no-fetch", action="store_true")
    b.add_argument("--fetch-only", action="store_true", help="only download raw pages (no Spark)")
    b.add_argument("--workers", type=int, default=1, help="parallel downloads (one scope per worker)")

    sub.add_parser("rebuild", help="delete the lake and replay all raw files")
    sub.add_parser("gold", help="rebuild dims, fact and marts from silver")
    sub.add_parser("dq", help="run data-quality checks only")
    e = sub.add_parser("export", help="write the dashboard snapshot (slim parquet) from the gold marts")
    e.add_argument("--out", default=None)
    r = sub.add_parser("report", help="write docs/findings.md from the marts")
    r.add_argument("--out", default=None)

    s = sub.add_parser("show", help="print a table, e.g. gold/mart_lead_lag")
    s.add_argument("table")
    s.add_argument("-n", type=int, default=20)
    s.add_argument("--where", default=None)
    s.add_argument("--order-by", default=None)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s", datefmt="%H:%M:%S"
    )
    logging.getLogger("py4j").setLevel(logging.WARNING)

    settings = load_settings(data_root=args.data_root)

    if args.cmd == "daily" and args.land_only:
        from freshlens.ingest.landing import land_daily
        from freshlens.pipeline import make_client

        print(land_daily(settings, make_client(settings), args.date))
        return 0

    if args.cmd == "backfill" and args.fetch_only:
        from concurrent.futures import ThreadPoolExecutor

        from freshlens.ingest.landing import history_scopes, land_history
        from freshlens.pipeline import make_client

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = [pool.submit(land_history, settings, make_client(settings), f) for f in history_scopes(settings)]
            for job in jobs:
                job.result()
        return 0

    from freshlens import pipeline, quality
    from freshlens.spark import get_spark

    spark = get_spark()
    try:
        if args.cmd == "daily":
            pipeline.run_daily(spark, settings, args.date, fetch=not args.no_fetch)
        elif args.cmd == "backfill":
            pipeline.run_backfill(spark, settings, fetch=not args.no_fetch)
        elif args.cmd == "rebuild":
            pipeline.rebuild(spark, settings)
        elif args.cmd == "gold":
            pipeline.refresh_gold(spark, settings)
        elif args.cmd == "dq":
            quality.run_checks(spark, settings, f"adhoc-{datetime.now():%Y%m%dT%H%M%S}", date.today())
        elif args.cmd == "export":
            from pathlib import Path

            from freshlens.export import export_snapshot

            print(export_snapshot(spark, settings, Path(args.out) if args.out else None))
        elif args.cmd == "report":
            from pathlib import Path

            from freshlens.report import write_findings

            print(write_findings(spark, settings, Path(args.out) if args.out else None))
        elif args.cmd == "show":
            layer, name = args.table.split("/", 1)
            df = spark.read.format("delta").load(settings.table(layer, name))
            if args.where:
                df = df.where(args.where)
            if args.order_by:
                df = df.orderBy(*[c.strip() for c in args.order_by.split(",")])
            df.show(args.n, truncate=False)
    except quality.DataQualityError as exc:
        logging.error("%s", exc)
        return 2
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Raw landing zone: API pages written to disk exactly as received (immutable JSON).

Layout::

    raw/daily/ingest_date=2026-11-24/run=20261124T221500/commodity=Tomato/page_00000000.json
    raw/history/scope=commodity-onion__market-lasalgaon/page_00000000.json.gz  (+ _SUCCESS)

* Every daily run is a new snapshot, so a later run that day can carry corrected prices.
  Silver keeps the latest version of each row.
* A history scope is resumable: pages already on disk are skipped and the job carries on from
  the next offset, which matters on a rate-limited API.
* History pages are requested with ``sort[Arrival_Date]``. Without a sort the API's offset paging is
  unstable: pages overlap, and for Azadpur tomato 34% of rows were silently never returned
  (3,490 rows fetched, only 2,310 unique). Each scope is checked for completeness after download.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from freshlens.config import Settings
from freshlens.ingest.api_client import DataGovClient

log = logging.getLogger(__name__)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def scope_slug(filters: dict[str, str]) -> str:
    return "__".join(f"{_slug(k)}-{_slug(v)}" for k, v in sorted(filters.items()))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a page atomically; ``.json.gz`` paths are gzip-compressed (raw stays byte-for-byte content)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, ensure_ascii=False).encode()
    tmp.write_bytes(gzip.compress(data, mtime=0) if path.name.endswith(".gz") else data)
    os.replace(tmp, path)


def read_page(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.name.endswith(".gz") else raw)


PAGE_GLOB = "page_*.json*"  # page_00000000.json or page_00000000.json.gz


def _envelope(source: str, resource_id: str, filters: dict, page) -> dict[str, Any]:
    return {
        "source": source,
        "resource_id": resource_id,
        "filters": filters,
        "offset": page.offset,
        "total": page.total,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "records": page.records,
    }


def land_daily(settings: Settings, client: DataGovClient, ingest_date: date) -> Path:
    """Snapshot today's prices for every configured commodity (all India)."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    run_dir = Path(settings.raw_root) / "daily" / f"ingest_date={ingest_date}" / f"run={run_id}"
    resource = settings.source["daily_resource_id"]
    total_rows = 0
    for commodity in settings.commodities:
        filters = {"commodity": commodity}
        for page in client.pages(resource, filters):
            if not page.records:
                break
            out = run_dir / f"commodity={_slug(commodity)}" / f"page_{page.offset:08d}.json.gz"
            _write_json_atomic(out, _envelope("daily", resource, filters, page))
            total_rows += len(page.records)
    log.info("daily landing %s: %d rows → %s", ingest_date, total_rows, run_dir)
    return run_dir


def history_scopes(settings: Settings) -> list[dict[str, str]]:
    """Backfill scope: the main Delhi terminal mandi for every commodity, plus both ends of every lane.

    ``history.extra_scopes`` in settings.yaml can add wider pulls (e.g. every Delhi mandi).
    """
    hub = settings.cfg.get("history", {}).get("hub_market", "Azadpur")
    scopes = []  # lanes first: they feed the spread and lead-lag marts
    for lane in settings.lanes:
        for market in (lane["destination"], lane["source"]):
            scopes.append({"Market": market, "Commodity": lane["commodity"]})
    scopes += [{"Market": hub, "Commodity": c} for c in settings.commodities]
    scopes += settings.cfg.get("history", {}).get("extra_scopes", []) or []
    unique = {scope_slug(s): s for s in scopes}
    return list(unique.values())


def land_history(settings: Settings, client: DataGovClient, filters: dict[str, str]) -> Path:
    """Download one history scope, resuming from whatever pages are already on disk."""
    resource = settings.source["history_resource_id"]
    scope_dir = Path(settings.raw_root) / "history" / f"scope={scope_slug(filters)}"
    if (scope_dir / "_SUCCESS").exists():
        log.info("history %s already complete — skipping", scope_dir.name)
        return scope_dir

    start = 0
    for existing in sorted(scope_dir.glob(PAGE_GLOB)):
        body = read_page(existing)
        start = max(start, body["offset"] + len(body["records"]))
    if start:
        log.info("history %s: resuming at offset %d", scope_dir.name, start)

    rows = 0
    sort = {"sort[Arrival_Date]": "asc"}  # stable ordering → no overlapping/missing pages
    for page in client.pages(resource, filters, start_offset=start, extra_params=sort):
        if not page.records:
            break
        _write_json_atomic(scope_dir / f"page_{page.offset:08d}.json.gz", _envelope("history", resource, filters, page))
        rows += len(page.records)
        if page.offset and page.offset % 10_000 < len(page.records):
            log.info("history %s: %d / %s", scope_dir.name, page.offset + len(page.records), page.total)
    scope_dir.mkdir(parents=True, exist_ok=True)
    check = completeness(scope_dir)
    (scope_dir / "_SUCCESS").write_text(json.dumps({"finished_at": datetime.now(UTC).isoformat(), **check}))
    log_fn = log.info if check["complete"] else log.warning
    log_fn("history %s: +%d rows, completeness %s", scope_dir.name, rows, check)
    return scope_dir


def completeness(scope_dir: Path) -> dict[str, Any]:
    """Compare distinct records on disk with the total the API reported."""
    total, seen, n = None, set(), 0
    for page in sorted(scope_dir.glob(PAGE_GLOB)):
        body = read_page(page)
        total = body.get("total") if body.get("total") is not None else total
        for rec in body["records"]:
            seen.add(json.dumps(rec, sort_keys=True))
            n += 1
    return {"total": total, "rows": n, "distinct": len(seen), "complete": total is not None and len(seen) >= int(total)}

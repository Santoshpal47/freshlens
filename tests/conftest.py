import json
from pathlib import Path

import pytest

from freshlens.config import load_settings


@pytest.fixture(scope="session")
def spark():
    import os

    os.environ.setdefault("FPR_SPARK_MASTER", "local[2]")
    os.environ.setdefault("FPR_SHUFFLE_PARTITIONS", "2")
    from freshlens.spark import get_spark

    s = get_spark("fpr-tests")
    yield s
    s.stop()


@pytest.fixture()
def settings(tmp_path):
    return load_settings(data_root=str(tmp_path / "data"))


def write_page(
    folder: Path,
    records: list[dict],
    offset: int = 0,
    fetched_at: str = "2026-11-24T10:00:00+00:00",
    source: str = "daily",
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"page_{offset:08d}.json"
    path.write_text(
        json.dumps(
            {
                "source": source,
                "resource_id": "x",
                "filters": {},
                "offset": offset,
                "total": len(records),
                "fetched_at": fetched_at,
                "records": records,
            }
        )
    )
    return path


def rec(
    market="Azadpur APMC",
    commodity="Tomato",
    day="24/11/2026",
    lo=1000,
    modal=1500,
    hi=2000,
    state="NCT of Delhi",
    district="Delhi",
    variety="Local",
    grade="FAQ",
):
    """A daily-feed style record (snake_case keys, numeric prices)."""
    return {
        "state": state,
        "district": district,
        "market": market,
        "commodity": commodity,
        "variety": variety,
        "grade": grade,
        "arrival_date": day,
        "min_price": lo,
        "max_price": hi,
        "modal_price": modal,
    }

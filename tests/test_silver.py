from datetime import date

from conftest import rec, write_page
from freshlens import bronze, silver


def _clean(spark, settings, tmp_path, records):
    write_page(tmp_path / "raw", records)
    df = bronze.read_raw_pages(spark, tmp_path / "raw", "daily", "t")
    return {(r["market_raw"], r["commodity"], r["variety"]): r for r in silver.clean(df, settings).collect()}


def test_typing_units_and_market_names(spark, settings, tmp_path):
    rows = _clean(spark, settings, tmp_path, [rec(market="  Azadpur   APMC ", lo=1000, modal=1550, hi=2000)])
    r = next(iter(rows.values()))
    assert r["market"] == "Azadpur"  # suffix stripped, whitespace collapsed
    assert r["arrival_date"] == date(2026, 11, 24)  # dd/MM/yyyy parsed
    assert r["modal_price_kg"] == 15.5  # ₹/quintal → ₹/kg
    assert r["dq_reason"] is None


def test_history_feed_shape_is_understood(spark, settings, tmp_path):
    hist = {
        "Arrival_Date": "03/11/2025",
        "Commodity": "Onion",
        "District": "Nashik",
        "Grade": "Local",
        "Market": "Lasalgaon",
        "Max_Price": "2,500",
        "Min_Price": "600",
        "Modal_Price": "1550",
        "State": "Maharashtra",
        "Variety": "Other",
        "Commodity_Code": "23",
    }
    write_page(tmp_path / "raw", [hist], source="history")
    r = silver.clean(bronze.read_raw_pages(spark, tmp_path / "raw", "history", "t"), settings).first()
    assert (r["market"], r["max_price"], r["modal_price_kg"], r["dq_reason"]) == ("Lasalgaon", 2500.0, 15.5, None)


def test_row_level_rules_flag_bad_rows(spark, settings, tmp_path):
    rows = _clean(
        spark,
        settings,
        tmp_path,
        [
            rec(variety="ok"),
            rec(variety="order", lo=1600, modal=1500),
            rec(variety="zero", lo=0, modal=0, hi=0),
            rec(variety="date", day="not-a-date"),
            rec(variety="unit", lo=100, modal=500_000, hi=600_000),
        ],
    )
    reasons = {k[2]: v["dq_reason"] for k, v in rows.items()}
    assert reasons == {
        "ok": None,
        "order": "min_above_modal",
        "zero": "bad_modal_price",
        "date": "bad_date",
        "unit": "implausible_price",
    }


def test_zero_min_max_means_not_reported(spark, settings, tmp_path):
    # e.g. Agra potato in 2017 reports only a modal price, with min = max = 0
    rows = _clean(spark, settings, tmp_path, [rec(lo=0, modal=510, hi=0)])
    r = next(iter(rows.values()))
    assert (r["min_price"], r["max_price"], r["modal_price"], r["dq_reason"]) == (None, None, 510.0, None)


def test_gzip_raw_pages_are_read(spark, settings, tmp_path):
    import gzip
    import json

    page = {"source": "daily", "offset": 0, "total": 1, "fetched_at": "2026-11-24T10:00:00+00:00", "records": [rec()]}
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / "page_00000000.json.gz").write_bytes(gzip.compress(json.dumps(page).encode()))
    df = bronze.read_raw_pages(spark, folder, "daily", "t")
    assert df is not None and df.count() == 1 and df.first()["market"] == "Azadpur APMC"

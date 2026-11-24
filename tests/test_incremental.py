"""MERGE semantics: re-runs are no-ops, corrections update, stale copies never win."""

from pyspark.sql import functions as F

from conftest import rec, write_page
from freshlens import pipeline


def _silver(spark, settings):
    return spark.read.format("delta").load(settings.table("silver", "prices"))


def _run(spark, settings, folder, batch):
    return pipeline._process_batch(spark, settings, folder, "daily", batch)


def test_rerun_is_idempotent_and_corrections_apply(spark, settings, tmp_path):
    day = tmp_path / "raw" / "d1"
    write_page(
        day / "run=1",
        [rec(modal=1500), rec(commodity="Onion", modal=2000, hi=2500), rec(variety="bad", lo=1600, modal=1500)],
        fetched_at="2026-11-24T10:00:00+00:00",
    )

    n, res = _run(spark, settings, day, "d1")
    assert (n, res.inserted, res.updated, res.quarantined) == (3, 2, 0, 1)

    _, res = _run(spark, settings, day, "d1")  # same input again
    assert (res.inserted, res.updated) == (0, 0)
    assert _silver(spark, settings).count() == 2
    assert spark.read.format("delta").load(settings.table("bronze", "prices")).count() == 3  # replaced, not appended

    # a later snapshot of the same day corrects the tomato price
    write_page(day / "run=2", [rec(modal=1700)], fetched_at="2026-11-24T18:00:00+00:00")
    _, res = _run(spark, settings, day, "d1")
    assert (res.inserted, res.updated) == (0, 1)
    tomato = _silver(spark, settings).where(F.col("commodity") == "Tomato").first()
    assert tomato["modal_price"] == 1700.0


def test_older_copy_does_not_overwrite_newer(spark, settings, tmp_path):
    new = tmp_path / "raw" / "new"
    old = tmp_path / "raw" / "old"
    write_page(new, [rec(modal=1700)], fetched_at="2026-11-24T18:00:00+00:00")
    write_page(old, [rec(market="Azadpur", modal=1500)], fetched_at="2026-11-01T00:00:00+00:00")
    _run(spark, settings, new, "new")
    _, res = _run(spark, settings, old, "old")  # e.g. a history re-download
    assert res.updated == 0
    assert _silver(spark, settings).first()["modal_price"] == 1700.0


def test_only_configured_commodities_reach_silver(spark, settings, tmp_path):
    day = tmp_path / "raw" / "d"
    write_page(day, [rec(commodity="Tomato"), rec(commodity="Green Peas"), rec(commodity="Banana - Green")])
    _, res = _run(spark, settings, day, "d")
    assert res.inserted == 1
    assert [r["commodity"] for r in _silver(spark, settings).collect()] == ["Tomato"]

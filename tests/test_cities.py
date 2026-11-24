"""Pan-India: config market names map onto silver's cleaned names, and city prices are medians."""

from datetime import date

from freshlens import marts
from freshlens.ingest.landing import history_scopes
from freshlens.silver import clean_market_name


def test_clean_market_name_matches_silver_rules():
    assert clean_market_name("  Azadpur   APMC ") == "Azadpur"
    assert clean_market_name("Jaipur (F&V)") == "Jaipur"
    assert clean_market_name("Binny Mill (F&V), Bangalore") == "Binny Mill (F&V), Bangalore"
    assert clean_market_name("Madanapalle", {"madanapalle": "Madanapalli"}) == "Madanapalli"


def test_every_configured_market_maps_to_its_city(settings):
    city_of = settings.market_city()
    for city, markets in settings.cities.items():
        for m in markets:
            assert city_of[clean_market_name(m).lower()] == city


def test_history_scopes_cover_every_city_market_and_item(settings):
    scopes = history_scopes(settings)
    n_markets = sum(len(ms) for ms in settings.cities.values())
    assert len(scopes) >= n_markets * len(settings.commodities)
    assert {"Market": "Lasalgaon", "Commodity": "Onion"} in scopes  # lane source


def test_city_price_is_the_median_of_its_markets(spark):
    rows = [
        (date(2025, 1, 1), "Bengaluru", "Binny Mill (F&V), Bangalore", 1, "Tomato", "Tomato", "vegetable", 20.0),
        (date(2025, 1, 1), "Bengaluru", "Bangalore", 1, "Tomato", "Tomato", "vegetable", 30.0),
        (date(2025, 1, 1), None, "Kolar", 1, "Tomato", "Tomato", "vegetable", 10.0),  # not a city market
    ]
    df = spark.createDataFrame(
        rows,
        "date date, city string, market string, commodity_key long, commodity string, "
        "display_name string, category string, modal_price_kg double",
    )
    out = marts.city_daily(df).collect()
    assert len(out) == 1 and out[0]["city"] == "Bengaluru" and out[0]["n_markets"] == 2
    assert out[0]["modal_price_kg"] in (20.0, 30.0)  # percentile_approx returns an actual value

from freshlens.ingest.api_client import Page
from freshlens.ingest.landing import land_history


class FakeClient:
    """Serves 5 records 2 per page; records whether a sort was requested."""

    def __init__(self, duplicate_page=False):
        self.recs = [{"Arrival_Date": f"0{i}/01/2024", "Modal_Price": str(i)} for i in range(1, 6)]
        self.duplicate_page = duplicate_page
        self.extra = None

    def pages(self, resource, filters, start_offset=0, extra_params=None):
        self.extra = extra_params
        for off in range(start_offset, 5, 2):
            src = 0 if (self.duplicate_page and off == 2) else off  # unstable server: page 2 repeats page 0
            yield Page(offset=off, total=5, records=self.recs[src : src + 2])


def _success(settings, filters):
    import json
    from pathlib import Path

    d = next((Path(settings.raw_root) / "history").glob("scope=*"))
    return json.loads((d / "_SUCCESS").read_text())


def test_history_is_sorted_and_complete(settings):
    client = FakeClient()
    land_history(settings, client, {"Market": "Azadpur", "Commodity": "Tomato"})
    assert client.extra == {"sort[Arrival_Date]": "asc"}
    assert _success(settings, None)["complete"] is True


def test_overlapping_pages_are_flagged_incomplete(settings):
    land_history(settings, FakeClient(duplicate_page=True), {"Market": "Azadpur", "Commodity": "Tomato"})
    s = _success(settings, None)
    assert (s["rows"], s["distinct"], s["complete"]) == (5, 3, False)

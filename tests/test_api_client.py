import pytest
import requests

from freshlens.ingest.api_client import ApiError, DataGovClient

SECRET = "super-secret-key"


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(dict(params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def page(records, total):
    return FakeResponse(200, {"status": "ok", "total": total, "records": records})


def client(session, **kw):
    return DataGovClient(SECRET, session=session, sleep=lambda s: None, page_size=2, **kw)


def test_paginates_until_total_using_server_page_size():
    # server caps pages at 2 rows; 5 rows total → 3 pages
    s = FakeSession([page([{"a": 1}, {"a": 2}], 5), page([{"a": 3}, {"a": 4}], 5), page([{"a": 5}], 5)])
    pages = list(client(s).pages("res", {"commodity": "Tomato"}))
    assert [p.offset for p in pages] == [0, 2, 4]
    assert sum(len(p.records) for p in pages) == 5
    assert s.calls[0]["filters[commodity]"] == "Tomato"


def test_stops_on_empty_page():
    s = FakeSession([page([], 0)])
    assert len(list(client(s).pages("res"))) == 1


def test_retries_429_and_network_errors():
    s = FakeSession(
        [
            FakeResponse(429, headers={"Retry-After": "1"}),
            requests.ConnectionError(f"https://x?api-key={SECRET}"),
            page([{"a": 1}], 1),
        ]
    )
    pages = list(client(s).pages("res"))
    assert pages[0].records == [{"a": 1}]
    assert len(s.calls) == 3


def test_gives_up_without_leaking_key():
    s = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(ApiError) as exc:
        list(client(s, max_retries=2).pages("res"))
    assert SECRET not in str(exc.value)


def test_non_retryable_status_fails_fast():
    s = FakeSession([FakeResponse(403)])
    with pytest.raises(ApiError, match="403"):
        list(client(s).pages("res"))
    assert len(s.calls) == 1

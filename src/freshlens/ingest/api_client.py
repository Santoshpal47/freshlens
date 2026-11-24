"""data.gov.in (OGD India) API client.

* paginates with offset/limit and trusts the server's own page size — the public sample key is
  silently capped at 10 rows, a registered key gets more;
* retries 429 / 5xx / network errors with exponential backoff (and honours Retry-After);
* sends its own User-Agent (the default python-requests one is tarpitted by the server);
* never lets the API key leak into exceptions or logs (requests puts it in the URL).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# data.gov.in tarpits the default "python-requests/x.y" User-Agent (requests hang until timeout),
# so the client always identifies itself.
USER_AGENT = "freshlens/0.1 (+https://github.com/Santoshpal47/freshlens)"


class ApiError(RuntimeError):
    pass


@dataclass
class Page:
    offset: int
    total: int | None
    records: list[dict[str, Any]]


class DataGovClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.data.gov.in/resource",
        page_size: int = 1000,
        timeout_s: float = 60,
        max_retries: int = 6,
        backoff_s: float = 2.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.session = session or requests.Session()
        if hasattr(self.session, "headers"):
            self.session.headers["User-Agent"] = USER_AGENT
        self._sleep = sleep

    # ------------------------------------------------------------------------------------
    def pages(
        self,
        resource_id: str,
        filters: dict[str, str] | None = None,
        start_offset: int = 0,
        extra_params: dict[str, str] | None = None,
    ) -> Iterator[Page]:
        """Yield every page of a resource for the given filters, starting at ``start_offset``."""
        offset = start_offset
        while True:
            params: dict[str, Any] = {
                "api-key": self._key,
                "format": "json",
                "limit": self.page_size,
                "offset": offset,
            }
            for k, v in (filters or {}).items():
                params[f"filters[{k}]"] = v
            params.update(extra_params or {})

            payload = self._get(resource_id, params)
            records = payload.get("records") or []
            total = _to_int(payload.get("total"))
            yield Page(offset=offset, total=total, records=records)

            offset += len(records)
            if not records or (total is not None and offset >= total):
                return

    # ------------------------------------------------------------------------------------
    def _get(self, resource_id: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{resource_id}"
        where = f"resource={resource_id} offset={params.get('offset')}"
        last_problem = "unknown error"
        for attempt in range(self.max_retries + 1):
            resp: requests.Response | None = None
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout_s)
            except requests.RequestException as exc:  # network trouble: retry
                last_problem = type(exc).__name__  # str(exc) would include the URL + key
            else:
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                    except ValueError:
                        last_problem = "non-JSON body"
                    else:
                        if str(payload.get("status", "ok")).lower() == "error":
                            raise ApiError(f"{where}: API error: {payload.get('message')}")
                        return payload
                elif resp.status_code in RETRYABLE_STATUS:
                    last_problem = f"HTTP {resp.status_code}"
                else:
                    raise ApiError(f"{where}: HTTP {resp.status_code} (not retryable)")

            if attempt == self.max_retries:
                break
            wait = self._retry_after(resp) or self.backoff_s * (2**attempt)
            log.warning("%s: %s — retry %d/%d in %.0fs", where, last_problem, attempt + 1, self.max_retries, wait)
            self._sleep(wait)
        raise ApiError(f"{where}: giving up after {self.max_retries} retries ({last_problem})")

    @staticmethod
    def _retry_after(resp: requests.Response | None) -> float | None:
        if resp is None or resp.status_code != 429:
            return None
        value = resp.headers.get("Retry-After", "")
        return float(value) if value.isdigit() else None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

"""Settings, paths and secrets.

All tunables live in ``config/settings.yaml``; this module only resolves paths and the API key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_GEO_SEED = PROJECT_ROOT / "config" / "mandi_geo.csv"


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    cfg: dict[str, Any]
    data_root: str
    geo_seed: str = str(DEFAULT_GEO_SEED)

    # ---- paths -------------------------------------------------------------------------
    @property
    def raw_root(self) -> str:
        return f"{self.data_root}/raw"

    def table(self, layer: str, name: str) -> str:
        """Path of a Delta table, e.g. table('silver', 'prices')."""
        return f"{self.data_root}/lake/{layer}/{name}"

    # ---- convenience accessors -----------------------------------------------------------
    @property
    def source(self) -> dict[str, Any]:
        return self.cfg["source"]

    @property
    def commodities(self) -> dict[str, str]:
        return self.cfg["commodities"]

    @property
    def display_names(self) -> dict[str, str]:
        names = self.cfg.get("display_names", {}) or {}
        return {c: names.get(c, c) for c in self.commodities}

    @property
    def cities(self) -> dict[str, list[str]]:
        """City → its wholesale markets, spelled as the API spells them (used for history filters)."""
        return self.cfg.get("cities") or {"Delhi NCR": [self.cfg.get("history", {}).get("hub_market", "Azadpur")]}

    def market_city(self) -> dict[str, str]:
        """Cleaned, lower-cased market name (as it appears in silver) → city."""
        from freshlens.silver import clean_market_name

        aliases = self.aliases.get("market", {})
        return {clean_market_name(m, aliases).lower(): city for city, ms in self.cities.items() for m in ms}

    @property
    def home_state(self) -> str:
        return self.cfg["home_state"]

    @property
    def lanes(self) -> list[dict[str, Any]]:
        return self.cfg["lanes"]

    @property
    def analysis(self) -> dict[str, Any]:
        return self.cfg["analysis"]

    @property
    def quality(self) -> dict[str, Any]:
        return self.cfg["quality"]

    @property
    def aliases(self) -> dict[str, dict[str, str]]:
        return self.cfg.get("aliases", {}) or {}


def load_settings(path: str | Path | None = None, data_root: str | None = None) -> Settings:
    load_dotenv()
    with open(path or DEFAULT_SETTINGS) as fh:
        cfg = yaml.safe_load(fh)
    root = data_root or os.environ.get("FPR_DATA_ROOT") or str(PROJECT_ROOT / "data")
    return Settings(cfg=cfg, data_root=root.rstrip("/"))


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("DATA_GOV_IN_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DATA_GOV_IN_API_KEY is not set. Get a free key at https://data.gov.in "
            "(My Account → Generate Key) and put it in .env"
        )
    return key

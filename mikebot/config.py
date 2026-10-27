"""Sports, tiers and runtime settings."""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - tzdata missing
    ET = timezone(timedelta(hours=-5))


@dataclass(frozen=True)
class Sport:
    key: str            # "NFL" — also the top-level data folder name
    espn_path: str      # path segment for the ESPN site API
    slug: str           # lower-case slug used by tout sites ("nfl-picks")
    total_odds: int = -110
    spread_odds: int = -110


SPORTS = {
    "NFL": Sport("NFL", "football/nfl", "nfl"),
    "NBA": Sport("NBA", "basketball/nba", "nba"),
    "MLB": Sport("MLB", "baseball/mlb", "mlb"),
    "NHL": Sport("NHL", "hockey/nhl", "nhl"),
}

# Sports MikeBot works by default (override with MIKEBOT_SPORTS=NFL,NBA,MLB).
DEFAULT_SPORTS = ("NFL", "NBA")

# T.A.G. tier thresholds (handoff v7): strong >=75, solid 55-74, split 35-54,
# weak <35, insufficient = no picks.
TIERS = (("strong", 75), ("solid", 55), ("split", 35), ("weak", 0))


def active_sports():
    raw = os.environ.get("MIKEBOT_SPORTS", "")
    keys = [k.strip().upper() for k in raw.split(",") if k.strip()] or list(DEFAULT_SPORTS)
    return [SPORTS[k] for k in keys if k in SPORTS]


def data_dir() -> Path:
    return Path(os.environ.get("MIKEBOT_DATA_DIR", "data"))


def today_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def shift_date(date: str, days: int) -> str:
    d = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")

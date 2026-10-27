"""ESPN public scoreboard client: schedule, market odds and final scores.

The site API (site.api.espn.com) needs no key. Its odds block has changed shape
over the years, so parsing reads every known layout and falls back to the
human-readable ``details`` string ("BOS -5.5").
"""

import re
from datetime import datetime

from .config import ET, Sport
from .http import fetch_json

BASE = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={dates}&limit=200"


def scoreboard(sport: Sport, date: str) -> dict:
    url = BASE.format(path=sport.espn_path, dates=date.replace("-", ""))
    return fetch_json(url)


def games_for(sport: Sport, date: str) -> list:
    return parse_scoreboard(scoreboard(sport, date), sport)


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().lower().lstrip("ou")
    if s in ("even", "pk", "ev"):
        return 100 if s != "pk" else 0
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _team(c: dict) -> dict:
    t = c.get("team") or {}
    rec = next((r.get("summary") for r in c.get("records") or [] if r.get("summary")), None)
    return {
        "abbr": t.get("abbreviation", ""),
        "name": t.get("displayName", ""),
        "short": t.get("shortDisplayName") or t.get("name", ""),
        "location": t.get("location", ""),
        "record": rec,
        "score": _num(c.get("score")),
    }


def _close(block: dict, *keys):
    """Read nested odds like moneyline.home.close.odds, preferring close over open."""
    cur = block
    for k in keys:
        cur = (cur or {}).get(k)
    if isinstance(cur, dict):
        for stage in ("close", "current", "open"):
            if stage in cur:
                return cur[stage]
    return cur


def parse_odds(odds_list: list, home: dict, away: dict) -> dict | None:
    if not odds_list:
        return None
    o = odds_list[0]
    out = {
        "provider": (o.get("provider") or {}).get("name"),
        "details": o.get("details"),
        "total": _num(o.get("overUnder")),
        "home_spread": None,
        "ml_home": None,
        "ml_away": None,
        "favorite": None,
    }
    hto, ato = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
    out["ml_home"] = _num(hto.get("moneyLine")) or _num((_close(o, "moneyline", "home") or {}).get("odds"))
    out["ml_away"] = _num(ato.get("moneyLine")) or _num((_close(o, "moneyline", "away") or {}).get("odds"))

    details = (o.get("details") or "").strip()
    m = re.match(r"^([A-Z]{2,4})\s+([-+]?\d+(?:\.\d+)?)$", details)
    if m:
        fav, line = m.group(1), abs(float(m.group(2)))
        out["favorite"] = fav
        out["home_spread"] = -line if fav == home["abbr"] else line
    elif details.upper() in ("EVEN", "PK", "PICK"):
        out["home_spread"] = 0
    else:
        hs = _num((_close(o, "pointSpread", "home") or {}).get("line"))
        if hs is None and o.get("spread") is not None:
            hs = _num(o.get("spread"))
        out["home_spread"] = hs
    if out["home_spread"] is not None:
        out["home_spread"] = _num(out["home_spread"])
        if out["favorite"] is None and out["home_spread"]:
            out["favorite"] = home["abbr"] if out["home_spread"] < 0 else away["abbr"]
    if out["total"] is None:
        out["total"] = _num((_close(o, "total", "over") or {}).get("line"))
    return out


def _local_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    except ValueError:
        return ""
    return dt.strftime("%-I:%M%p").lower().rstrip("m")


def parse_scoreboard(data: dict, sport: Sport) -> list:
    games = []
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): _team(c) for c in comp.get("competitors") or []}
        if "home" not in sides or "away" not in sides:
            continue
        st = (ev.get("status") or comp.get("status") or {}).get("type") or {}
        games.append({
            "game_id": f"{sport.key}-{ev.get('id')}",
            "espn_id": ev.get("id"),
            "sport": sport.key,
            "start": ev.get("date"),
            "game_time": _local_time(ev.get("date") or ""),
            "week": (ev.get("week") or data.get("week") or {}).get("number"),
            "away": sides["away"],
            "home": sides["home"],
            "matchup": f"{sides['away']['abbr']} @ {sides['home']['abbr']}",
            "state": st.get("state", "pre"),
            "completed": bool(st.get("completed")),
            "status_detail": st.get("shortDetail") or st.get("description"),
            "odds": parse_odds(comp.get("odds") or [], sides["home"], sides["away"]),
        })
    games.sort(key=lambda g: (g["start"] or "", g["matchup"]))
    return games

"""MikeBot's jobs: Daily Prep, Daily Pull, Daily Reflection, briefing."""

import os

from . import briefing, deliver, espn, store
from .config import active_sports, data_dir, now_iso, shift_date
from .grading import grade_day, update_ledger
from .http import FetchError
from .scoring import score_all
from .sources import get_sources


def _merge_games(old_games, new_games):
    """Refresh schedule/score fields but keep consensus fields from the old file."""
    old = {g["game_id"]: g for g in old_games}
    out = []
    for g in new_games:
        prev = old.get(g["game_id"], {})
        # keep the pre-game line if the fresh scoreboard dropped the odds block
        if g.get("odds") is None and prev.get("odds"):
            g["odds"] = prev["odds"]
        out.append({**prev, **g})
    return out


def prep(sport, date, log=print):
    """Daily Prep: schedule + market lines -> picks.json skeleton."""
    games = espn.games_for(sport, date)
    day = store.load_day(sport.key, date) or {
        "date": date, "sport": sport.key, "generated_at": None,
        "sources": [], "games": [], "picks": [], "source_runs": [],
    }
    day["games"] = _merge_games(day.get("games", []), games)
    day["generated_at"] = now_iso()
    log(f"[{sport.key} {date}] prep: {len(games)} games")
    return day


def pull(sport, date, log=print, only=None):
    """Daily Pull: run every source, merge picks, score tiers."""
    day = prep(sport, date, log)
    if not day["games"]:
        return day
    old_by_via = {}
    for p in day.get("picks", []):
        old_by_via.setdefault(p.get("via", p["source_id"]), []).append(p)
    runs, picks = [], []
    for src in get_sources(only):
        r = src.pull(sport, date, day["games"])
        for p in r["picks"]:
            p["via"] = src.id
        runs.append({k: r[k] for k in ("source_id", "status", "note", "checked")} | {"picks": len(r["picks"])})
        # A source whose article vanished later in the day keeps its earlier picks.
        picks.extend(r["picks"] or old_by_via.get(src.id, []))
        old_by_via.pop(src.id, None)
        log(f"[{sport.key} {date}]   {src.id:<10} {r['status']:<7} {len(r['picks'])} picks  {r['note']}")
        if os.environ.get("MIKEBOT_DEBUG"):
            games = {g["game_id"]: g["matchup"] for g in day["games"]}
            for p in r["picks"]:
                log(f"      {games.get(p['game_id'])}: {p['market']} {p['side']} [{p['confidence']}] <- {p['notes']!r}")
    for rest in old_by_via.values():  # sources not run this time (--only)
        picks.extend(rest)
    day["picks"] = picks
    day["source_runs"] = runs
    day["sources"] = sorted({p["source_id"] for p in day["picks"]})
    score_all(day["games"], day["picks"])
    tiers = {}
    for g in day["games"]:
        tiers[g["tier"]] = tiers.get(g["tier"], 0) + 1
    log(f"[{sport.key} {date}] pull: {len(day['picks'])} picks, tiers {tiers}")
    return day


def reflect(sport, date, log=print):
    """Daily Reflection: final scores -> settled_result on every pick -> ledger."""
    day = store.load_day(sport.key, date)
    if not day:
        log(f"[{sport.key} {date}] reflect: no picks.json, nothing to grade")
        return None
    day["games"] = _merge_games(day["games"], espn.games_for(sport, date))
    counts = grade_day(day)
    day["graded_at"] = now_iso()
    if counts["pending"] == 0:
        led = update_ledger(store.ledger(), sport.key, date, day)
        store.save_ledger(led)
    log(f"[{sport.key} {date}] reflect: graded {counts['graded']}, pending {counts['pending']}")
    return day


def daily(date, *, sports=None, send=False, log=print, write=True):
    """The full morning run for every active sport, then the briefing."""
    sports = sports or active_sports()
    yday = shift_date(date, -1)
    report = {"at": now_iso(), "job": "daily", "date": date, "sports": {}, "errors": []}
    days, recaps = [], []
    for sport in sports:
        try:
            graded = reflect(sport, yday, log)
            if graded:
                recaps.append((sport.key, yday, graded))
                if write:
                    store.save_day(sport.key, yday, graded)
        except FetchError as e:
            report["errors"].append(f"{sport.key} reflect: {e}")
            log(f"[{sport.key}] reflect failed: {e}")
        try:
            day = pull(sport, date, log)
        except FetchError as e:
            report["errors"].append(f"{sport.key} pull: {e}")
            log(f"[{sport.key}] pull failed: {e}")
            continue
        report["sports"][sport.key] = {"games": len(day["games"]), "picks": len(day["picks"])}
        if day["games"]:
            days.append((sport.key, day))
            if write:
                store.save_day(sport.key, date, day)

    html = briefing.render_html(date, days, recaps, store.ledger())
    text = briefing.render_text(date, days, recaps)
    if write:
        bdir = data_dir() / "briefings" / date
        store.save_json(bdir / "summary.json", report)
        (bdir / "briefing.html").write_text(html)
        (bdir / "briefing.txt").write_text(text)
    report["delivery"] = []
    if send and days:
        for fn, args in ((deliver.send_email, (briefing.subject(date), html, text)), (deliver.send_discord, (text,))):
            try:
                report["delivery"].append(fn(*args))
            except Exception as e:  # delivery must never lose the run's data
                report["delivery"].append(f"{fn.__name__} failed: {e}")
        log("delivery: " + "; ".join(report["delivery"]))
    if write:
        store.log_run(report)
    return report, html, text

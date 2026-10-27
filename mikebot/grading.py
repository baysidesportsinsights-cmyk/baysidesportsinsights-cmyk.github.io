"""Daily Reflection: grade picks against final scores and keep source records."""

from .config import SPORTS


def grade_pick(pick, game):
    """Return 'win' | 'loss' | 'push' | None (not gradable yet)."""
    if not game or not game.get("completed"):
        return None
    hs, as_ = game["home"].get("score"), game["away"].get("score")
    if hs is None or as_ is None:
        return None
    side = pick["side"]
    if pick["market"] == "total":
        line = side.get("line")
        if line is None:
            line = (game.get("odds") or {}).get("total")
        if line is None or side.get("ou") not in ("over", "under"):
            return None
        diff = (hs + as_) - line
        if diff == 0:
            return "push"
        return "win" if (diff > 0) == (side["ou"] == "over") else "loss"

    team = side.get("team")
    if team not in (game["home"]["abbr"], game["away"]["abbr"]):
        return None
    is_home = team == game["home"]["abbr"]
    margin = (hs - as_) if is_home else (as_ - hs)
    if pick["market"] == "moneyline":
        return "push" if margin == 0 else ("win" if margin > 0 else "loss")
    line = side.get("line")
    if line is None:
        home_spread = (game.get("odds") or {}).get("home_spread")
        if home_spread is None:
            return None
        line = home_spread if is_home else -home_spread
    adj = margin + line
    return "push" if adj == 0 else ("win" if adj > 0 else "loss")


def pick_odds(pick, game):
    if pick.get("odds"):
        return pick["odds"]
    if pick["market"] == "moneyline" and game and game.get("odds"):
        o = game["odds"]
        key = "ml_home" if pick["side"]["team"] == game["home"]["abbr"] else "ml_away"
        if o.get(key):
            return o[key]
    sport = SPORTS.get((game or {}).get("sport", ""), None)
    return sport.spread_odds if sport else -110


def profit_units(res, odds, units=1):
    if res == "win":
        return round(units * (odds / 100 if odds > 0 else 100 / abs(odds)), 3)
    if res == "loss":
        return -units
    return 0.0


def grade_day(day):
    """Grade every ungraded pick in a picks.json dict in place. Returns counts."""
    games = {g["game_id"]: g for g in day.get("games", [])}
    graded = 0
    for p in day.get("picks", []):
        if p.get("settled_result"):
            continue
        g = games.get(p["game_id"])
        res = grade_pick(p, g)
        if res:
            p["settled_result"] = res
            p["profit_units"] = profit_units(res, pick_odds(p, g), p.get("units") or 1)
            graded += 1
    pending = sum(1 for p in day.get("picks", []) if not p.get("settled_result"))
    return {"graded": graded, "pending": pending}


def summarize(picks):
    rec = {"win": 0, "loss": 0, "push": 0, "units": 0.0}
    for p in picks:
        r = p.get("settled_result")
        if r in rec:
            rec[r] += 1
            rec["units"] = round(rec["units"] + (p.get("profit_units") or 0), 3)
    return rec


def update_ledger(ledger, sport, date, day):
    """ledger = {sport: {source_id: {win, loss, push, units, days: [dates]}}} plus tier records."""
    if date in ledger.setdefault("_graded_days", {}).setdefault(sport, []):
        return ledger
    settled = [p for p in day.get("picks", []) if p.get("settled_result")]
    if not settled:
        return ledger
    book = ledger.setdefault(sport, {})
    for p in settled:
        r = book.setdefault(p["source_id"], {"win": 0, "loss": 0, "push": 0, "units": 0.0})
        r[p["settled_result"]] += 1
        r["units"] = round(r["units"] + (p.get("profit_units") or 0), 3)
    # consensus record by tier: did the consensus side cover / win?
    tiers = ledger.setdefault("_tiers", {}).setdefault(sport, {})
    for g in day.get("games", []):
        if not g.get("consensus_side"):
            continue
        votes = [p for p in settled if p["game_id"] == g["game_id"]
                 and p["market"] != "total" and p["side"].get("team") == g["consensus_side"]]
        if not votes:
            continue
        res = votes[0]["settled_result"]
        t = tiers.setdefault(g["tier"], {"win": 0, "loss": 0, "push": 0})
        t[res] += 1
    ledger["_graded_days"][sport].append(date)
    return ledger

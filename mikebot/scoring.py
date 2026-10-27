"""Game consensus and tier scores (T.A.G. formula, handoff v7).

tier_score = agreement_rate * 80 + min(source_count, 8) * 2
strong >= 75, solid 55-74, split 35-54, weak < 35, insufficient = no picks.
Side picks (moneyline / spread) and totals are scored separately; the game's
tier follows its side consensus, or its total consensus when no side picks.
"""

from collections import Counter

from .config import TIERS


def tier_for(score, n):
    if not n:
        return "insufficient"
    return next(name for name, floor in TIERS if score >= floor)


def _consensus(keys):
    if not keys:
        return None, 0.0
    counts = Counter(keys)
    top, n = counts.most_common(1)[0]
    if len(counts) > 1 and counts.most_common(2)[1][1] == n:
        top = None  # dead even split: no consensus side
    return top, n / len(keys)


def score_game(game, picks):
    mine = [p for p in picks if p["game_id"] == game["game_id"]]
    # one vote per source per bucket so a source with ML + spread on the same team counts once
    side_votes = {p["source_id"]: p["side"]["team"] for p in mine if p["market"] != "total" and p["side"].get("team")}
    total_votes = {p["source_id"]: p["side"]["ou"] for p in mine if p["market"] == "total" and p["side"].get("ou")}

    side, side_rate = _consensus(list(side_votes.values()))
    ou, ou_rate = _consensus(list(total_votes.values()))
    side_n, ou_n = len(side_votes), len(total_votes)

    def score(rate, n, top):
        if not n:
            return 0
        return round((rate if top else 0.5) * 80 + min(n, 8) * 2)

    side_score, ou_score = score(side_rate, side_n, side), score(ou_rate, ou_n, ou)
    use_side = side_n > 0
    tier_score = side_score if use_side else ou_score
    n = side_n if use_side else ou_n
    team = None
    if side:
        team = game["home"] if side == game["home"]["abbr"] else game["away"]
    return {
        "consensus_side": side,
        "consensus_team": team["name"] if team else None,
        "consensus_total": ou,
        "side_score": side_score,
        "total_score": ou_score,
        "tier_score": tier_score,
        "tier": tier_for(tier_score, n),
        "source_count": len({p["source_id"] for p in mine}),
        "split": (use_side and side is None) or (use_side and side_rate < 1.0),
    }


def score_all(games, picks):
    for g in games:
        g.update(score_game(g, picks))
    return games

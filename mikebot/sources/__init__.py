"""Tout sources. Each source turns (sport, date, games) into picks.

A source never raises: failures come back as status "failed" with a note, so
one blocked site never stops the daily run.
"""

import json
import re
from datetime import datetime

from ..config import data_dir
from ..http import FetchError, fetch
from .extract import extract_picks, html_to_text, team_words

MONTHS = "january february march april may june july august september october november december".split()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def date_tokens(date: str) -> set:
    d = datetime.strptime(date, "%Y-%m-%d")
    return {
        f"{d.month}-{d.day}-{d.year}",
        f"{d.month:02d}-{d.day:02d}-{d.year}",
        d.strftime("%Y-%m-%d"),
        f"{MONTHS[d.month - 1]}-{d.day}-{d.year}",
        f"{MONTHS[d.month - 1][:3]}-{d.day}-{d.year}",
    }


DATE_IN_SLUG = re.compile(
    r"(\d{1,2}-\d{1,2}-20\d\d|20\d\d-\d{2}-\d{2}|(?:" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*-\d{1,2}-20\d\d)"
)


def link_matches(url: str, game: dict, date: str) -> bool:
    slug = url.lower()
    for side in ("away", "home"):
        words = [slugify(w) for w in team_words(game[side]) if len(w) > 3 or not w.isupper()]
        if not any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", slug) for w in words if w):
            return False
    dates = DATE_IN_SLUG.findall(slug)
    return not dates or bool(set(dates) & date_tokens(date))


def result(source_id, status, picks=None, note="", checked=0):
    return {"source_id": source_id, "status": status, "picks": picks or [], "note": note, "checked": checked}


class IndexArticleSource:
    """Index page -> per-game article links -> picks from article text."""

    type = "expert"

    def __init__(self, sid, name, index_urls, link_re, article_url=None, max_articles=20):
        self.id, self.name = sid, name
        self.index_urls = index_urls      # {sport_key: url}
        self.link_re = link_re            # regex with one group = absolute or relative url
        self.article_url = article_url    # optional fn(sport, game, date) -> guessed url
        self.max_articles = max_articles

    def links(self, sport, date):
        url = self.index_urls.get(sport.key)
        if not url:
            return None
        page = fetch(url)
        root = re.match(r"https?://[^/]+", url).group(0)
        out = []
        for m in re.finditer(self.link_re.format(slug=sport.slug), page):
            href = m.group(1)
            href = href if href.startswith("http") else root + href
            if href not in out:
                out.append(href)
        return out

    def pull(self, sport, date, games):
        try:
            links = self.links(sport, date)
        except FetchError as e:
            return result(self.id, "failed", note=f"index: {e}")
        if links is None:
            return result(self.id, "skipped", note=f"no {sport.key} index")
        picks, checked, errors = [], 0, []
        for game in games:
            if checked >= self.max_articles:
                break
            cands = [u for u in links if link_matches(u, game, date)]
            if not cands and self.article_url:
                cands = [self.article_url(sport, game, date)]
            if not cands:
                continue
            checked += 1
            try:
                text = html_to_text(fetch(cands[0], retries=1))
            except FetchError as e:
                errors.append(str(e))
                continue
            for p in extract_picks(text, game):
                picks.append(make_pick(self.id, game, p, url=cands[0]))
        status = "ok" if picks else ("failed" if errors and len(errors) == checked else "empty")
        note = f"{len(links)} links, {checked} articles" + (f", {len(errors)} errors" if errors else "")
        return result(self.id, status, picks, note, checked)


def make_pick(source_id, game, p, url=None):
    side = dict(p["side"])
    odds = side.pop("odds", None)
    return {
        "source_id": source_id,
        "game_id": game["game_id"],
        "market": p["market"],
        "side": side,
        "odds": odds,
        "units": p.get("units", 1),
        "confidence": p.get("confidence", "inferred"),
        "settled_result": None,
        "notes": p.get("quote", ""),
        "url": url,
    }


def _pickdawgz_guess(sport, game, date):
    d = datetime.strptime(date, "%Y-%m-%d")
    a, h = slugify(game["away"]["name"]), slugify(game["home"]["name"])
    return (f"https://pickdawgz.com/{sport.slug}-picks/{a}-vs-{h}-prediction-"
            f"{d.month}-{d.day}-{d.year}-todays-{sport.slug}-picks/")


class ManualSource:
    """Picks dropped in by hand or by a Claude session: <SPORT>/<date>/manual.json.

    Format: {"picks": [{"source_id": "vsin_peterson", "game": "BOS @ NYK" | game_id,
              "market": "spread", "team": "BOS", "line": -5.5, "ou": null,
              "odds": -110, "confidence": "confirmed", "notes": "..."}]}
    """

    id, name, type = "manual", "Manual / Claude-pulled", "mixed"

    def pull(self, sport, date, games):
        path = data_dir() / sport.key / date / "manual.json"
        if not path.exists():
            return result(self.id, "empty", note="no manual.json")
        try:
            rows = json.loads(path.read_text()).get("picks", [])
        except (OSError, ValueError) as e:
            return result(self.id, "failed", note=str(e))
        by_key = {g["game_id"]: g for g in games} | {g["matchup"]: g for g in games}
        picks, missed = [], 0
        for r in rows:
            g = by_key.get(r.get("game_id") or r.get("game"))
            if not g:
                missed += 1
                continue
            side = {"team": r.get("team"), "line": r.get("line"), "ou": r.get("ou")}
            if r.get("odds") is not None:
                side["odds"] = r["odds"]
            p = make_pick(r.get("source_id", "manual"), g,
                          {"market": r.get("market", "moneyline"), "side": side,
                           "confidence": r.get("confidence", "confirmed"),
                           "units": r.get("units", 1), "quote": r.get("notes", "")},
                          url=r.get("url"))
            picks.append(p)
        note = f"{len(picks)} picks" + (f", {missed} unmatched" if missed else "")
        return result(self.id, "ok" if picks else "empty", picks, note)


SOURCES = [
    IndexArticleSource(
        "pickdawgz", "PickDawgz",
        {"NFL": "https://pickdawgz.com/nfl-picks/", "NBA": "https://pickdawgz.com/nba-picks/",
         "MLB": "https://pickdawgz.com/mlb-picks/", "NHL": "https://pickdawgz.com/nhl-picks/"},
        r'href="((?:https://pickdawgz\.com)?/{slug}-picks/[a-z0-9-]+-prediction[a-z0-9-]*/?)"',
        article_url=_pickdawgz_guess,
    ),
    IndexArticleSource(
        "pickswise", "Pickswise",
        {"NFL": "https://www.pickswise.com/nfl/picks/", "NBA": "https://www.pickswise.com/nba/picks/",
         "MLB": "https://www.pickswise.com/mlb/picks/", "NHL": "https://www.pickswise.com/nhl/picks/"},
        r'href="((?:https://www\.pickswise\.com)?/{slug}/picks/[a-z0-9-]+-(?:predictions?|picks?)[a-z0-9-]*/?)"',
    ),
    IndexArticleSource(
        "docsports", "Doc's Sports",
        {"NFL": "https://www.docsports.com/free-picks/football/",
         "NBA": "https://www.docsports.com/free-picks/nba/"},
        r'href="((?:https://www\.docsports\.com)?/free-picks/(?:football|nba|basketball)/20\d\d/[a-z0-9-]+\.html)"',
    ),
    ManualSource(),
]


def get_sources(only=None):
    return [s for s in SOURCES if not only or s.id in only]

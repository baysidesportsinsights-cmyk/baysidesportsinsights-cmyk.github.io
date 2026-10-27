"""Turn tout article text into structured picks.

Tout sites phrase picks in a handful of ways ("I am backing the Celtics",
"Pick: Celtics -5.5", "Best bet: Over 221.5"). Rather than one parser per site,
sources hand their article text here along with the game, and this module finds
the selection and maps team words onto the game's two teams.
"""

import html as htmllib
import re

# Selection text runs to the end of the sentence; a dot between digits (-4.5) isn't one.
SEL = r"(?P<sel>(?:[^.!?\n]|(?<=\d)\.(?=\d)){{2,{n}}})"

# Explicit pick statements -> "confirmed".
CONFIRMED = [
    r"\bI(?:'m| am)\s+(?:backing|taking|playing|betting|siding with|going with|riding)\s+" + SEL.format(n=80),
    r"\b(?:Pick|Prediction|Best Bet|Our Pick|The Pick|Final Pick|Play)\s*[:\-–—]\s*" + SEL.format(n=80),
    r"\bPlays?\s+on\s+" + SEL.format(n=80),
]
# Softer phrasing -> "inferred".
INFERRED = [
    r"\b(?:lean|like|prefer|recommend)\s+(?:the\s+)?" + SEL.format(n=60),
    r"\b(?:back|take)\s+the\s+" + SEL.format(n=60),
]

NUM = r"[-+]?\d+(?:\.\d+)?"


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</div>", "\n", html)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", html))
    text = text.replace("’", "'").replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def team_words(team: dict) -> list:
    """Words that identify a team in prose, longest first."""
    words = {team.get("name", ""), team.get("short", ""), team.get("location", "")}
    words |= {team.get("abbr", "")}
    if team.get("name"):
        words.add(team["name"].split()[-1])  # nickname: "Celtics", "Sox"
    return sorted((w for w in words if w and len(w) >= 2), key=len, reverse=True)


def which_team(sel: str, game: dict):
    """Return 'home' / 'away' if the selection names exactly one team."""
    hits = {}
    for side in ("home", "away"):
        for w in team_words(game[side]):
            pat = r"\b" + re.escape(w) + r"\b"
            flags = 0 if w.isupper() and len(w) <= 4 else re.I
            m = re.search(pat, sel, flags)
            if m:
                hits[side] = min(hits.get(side, 10**6), m.start())
                break
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) == 2:  # "Celtics to beat the Knicks" -> first named
        return min(hits, key=hits.get)
    return None


def parse_selection(sel: str, game: dict):
    """Selection text -> (market, side dict) or None."""
    s = sel.strip()
    m = re.search(r"\b(over|under)\s*(" + NUM + r")?", s, re.I)
    team_side = which_team(s, game)
    if m and (team_side is None or re.match(r"\s*(the\s+)?(over|under)", s, re.I)):
        return "total", {"team": None, "line": _f(m.group(2)), "ou": m.group(1).lower()}
    if team_side is None:
        return None
    abbr = game[team_side]["abbr"]
    after = s
    for w in team_words(game[team_side]):
        mm = re.search(r"\b" + re.escape(w) + r"\b", s, re.I)
        if mm:
            after = s[mm.end():]
            break
    if re.match(r"\s*(?:\(|on the\s+)?(?:ML|moneyline|money line|to win|straight up)\b", after, re.I):
        return "moneyline", {"team": abbr, "line": None, "ou": None}
    sm = re.match(r"\s*\(?\s*(" + NUM + r")(?!\d)", after)
    if sm:
        line = _f(sm.group(1))
        # American odds (-150, +130) are moneylines, spreads are small numbers.
        if abs(line) >= 100:
            return "moneyline", {"team": abbr, "line": None, "ou": None, "odds": int(line)}
        return "spread", {"team": abbr, "line": line, "ou": None}
    if re.search(r"\b(run ?line|puck ?line|spread|ATS|points)\b", after[:40], re.I):
        return "spread", {"team": abbr, "line": None, "ou": None}
    return "moneyline", {"team": abbr, "line": None, "ou": None}


def _f(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def extract_picks(text: str, game: dict, *, max_picks: int = 3) -> list:
    """All distinct picks for one game found in article text."""
    found, seen = [], set()
    for confidence, patterns in (("confirmed", CONFIRMED), ("inferred", INFERRED)):
        for pat in patterns:
            for m in re.finditer(pat, text, re.I):
                parsed = parse_selection(m.group("sel"), game)
                if not parsed:
                    continue
                market, side = parsed
                key = (market, side.get("team"), side.get("ou"))
                if key in seen:
                    continue
                # A side and a total can both be picks; two different sides can't.
                if market != "total" and any(k[0] != "total" and k[1] != side["team"] for k in seen):
                    continue
                seen.add(key)
                found.append({"market": market, "side": side, "confidence": confidence,
                              "quote": m.group(0).strip()[:140]})
        if found:
            break  # confirmed picks win; don't add softer guesses
    return found[:max_picks]

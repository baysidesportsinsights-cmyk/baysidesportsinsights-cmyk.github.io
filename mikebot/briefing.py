"""The daily briefing: phone-friendly HTML email (table layout, inline styles,
no JS) plus a plain-text twin for Discord and email fallbacks."""

from datetime import datetime
from html import escape

from .grading import summarize

NAVY, CREAM, INK, MUTED = "#0f1f3a", "#f6f3ec", "#1c2433", "#6b7280"
TIER_COLOR = {"strong": "#15803d", "solid": "#1d4ed8", "split": "#b45309", "weak": "#6b7280", "insufficient": "#9ca3af"}
TIER_LABEL = {"strong": "Strong signal", "solid": "Solid signal", "split": "Split", "weak": "Weak", "insufficient": "No picks yet"}
FONT = "-apple-system,'Helvetica Neue',Arial,sans-serif"


def fmt_line(v):
    if v is None:
        return ""
    return f"+{v:g}" if v > 0 else f"{v:g}"


def pick_label(p):
    s = p["side"]
    if p["market"] == "total":
        return f"{(s.get('ou') or '').title()} {s['line']:g}" if s.get("line") is not None else (s.get("ou") or "").title()
    if p["market"] == "spread":
        return f"{s['team']} {fmt_line(s.get('line'))}".strip()
    odds = f" ({fmt_line(p['odds'])})" if p.get("odds") else ""
    return f"{s['team']} ML{odds}"


def market_line(g):
    o = g.get("odds") or {}
    bits = []
    if o.get("home_spread") is not None:
        hs = o["home_spread"]
        bits.append("PK" if hs == 0 else f"{g['home']['abbr']} {fmt_line(hs)}")
    if o.get("total") is not None:
        bits.append(f"O/U {o['total']:g}")
    return " · ".join(bits)


def pretty_date(date):
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def subject(date):
    return f"🤖 MikeBot Daily Briefing — {pretty_date(date)}"


def _rec(r):
    s = f"{r['win']}-{r['loss']}" + (f"-{r['push']}" if r["push"] else "")
    return f"{s} ({r['units']:+.2f}u)"


def _chip(p):
    mark = "✓" if p["confidence"] == "confirmed" else "~"
    return (f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:3px 8px;border:1px solid #c7d2e0;'
            f'border-radius:12px;background:#eef3fa;font:12px Menlo,Consolas,monospace;color:{INK}">'
            f'{escape(pick_label(p))} <span style="color:{MUTED}">{escape(p["source_id"])} {mark}</span></span>')


def _game_card(g, picks):
    color = TIER_COLOR[g.get("tier", "insufficient")]
    score = g.get("tier_score", 0)
    rec = f' <span style="color:{MUTED};font-size:12px">({escape(g["away"]["record"] or "")} / {escape(g["home"]["record"] or "")})</span>' if g["away"].get("record") else ""
    cons = ""
    if g.get("consensus_side") or g.get("consensus_total"):
        parts = [x for x in (g.get("consensus_side"), (g.get("consensus_total") or "").title()) if x]
        cons = f'<div style="margin-top:6px;font-size:13px;color:{INK}"><b>Consensus:</b> {escape(" + ".join(parts))}</div>'
    chips = "".join(_chip(p) for p in picks)
    bar = (f'<div style="margin-top:8px;height:6px;background:#e5e7eb;border-radius:3px">'
           f'<div style="width:{score}%;height:6px;background:{color};border-radius:3px"></div></div>') if score else ""
    return (f'<tr><td style="padding:12px 14px;border-left:4px solid {color};background:#fff;border-bottom:8px solid {CREAM}">'
            f'<div style="font:bold 18px Georgia,serif;color:{INK}">{escape(g["matchup"])}{rec}</div>'
            f'<div style="font-size:12px;color:{MUTED}">{escape(g.get("game_time") or "")} ET · {escape(market_line(g))}'
            f'{" · score " + str(score) if score else ""}</div>{cons}'
            f'<div style="margin-top:6px">{chips}</div>{bar}</td></tr>')


def _sport_section(sport_key, day):
    games, picks = day.get("games", []), day.get("picks", [])
    by_game = {}
    for p in picks:
        by_game.setdefault(p["game_id"], []).append(p)
    counts = {t: sum(1 for g in games if g.get("tier") == t) for t in TIER_COLOR}
    strip = (f'{len(games)} games · {len(picks)} picks · '
             f'{counts["strong"]} strong · {counts["solid"]} solid · {counts["split"]} split')
    rows = [f'<tr><td style="padding:16px 4px 6px;font:bold 15px {FONT};color:{NAVY};letter-spacing:.06em">'
            f'{escape(sport_key)} <span style="font-weight:normal;color:{MUTED};font-size:12px">{strip}</span></td></tr>']
    srcs = day.get("source_runs") or []
    bad = [s for s in srcs if s["status"] == "failed"]
    if bad or (games and len(picks) == 0):
        msg = "No tout picks found yet — market lines only." if not picks else ""
        if bad:
            msg += (" " if msg else "") + "Sources down: " + ", ".join(f'{s["source_id"]} ({s["note"]})' for s in bad)
        rows.append(f'<tr><td style="padding:8px 12px;background:#fff7e6;border:1px solid #f5d08a;font-size:12px;color:#7a4b00">'
                    f'⚠️ {escape(msg)}</td></tr>')
    order = ("strong", "solid", "split", "weak", "insufficient")
    for g in sorted(games, key=lambda g: (order.index(g.get("tier", "insufficient")), -g.get("tier_score", 0), g.get("start") or "")):
        rows.append(_game_card(g, by_game.get(g["game_id"], [])))
    return "".join(rows)


def _recap_section(recaps):
    if not recaps:
        return ""
    lines = []
    for sport_key, date, day in recaps:
        rec = summarize(day.get("picks", []))
        if not (rec["win"] + rec["loss"] + rec["push"]):
            continue
        tier_bits = []
        for g in day.get("games", []):
            if g.get("tier") == "strong" and g.get("consensus_side"):
                res = next((p["settled_result"] for p in day["picks"] if p["game_id"] == g["game_id"]
                            and p["side"].get("team") == g["consensus_side"] and p.get("settled_result")), None)
                if res:
                    tier_bits.append(f'{g["consensus_side"]} {"✅" if res == "win" else "❌" if res == "loss" else "➖"}')
        strong = f' · strong: {", ".join(tier_bits)}' if tier_bits else ""
        lines.append(f"<b>{escape(sport_key)}</b> {escape(date)}: all picks {_rec(rec)}{escape(strong)}")
    if not lines:
        return ""
    return (f'<tr><td style="padding:12px 14px;background:#fff;border-left:4px solid {NAVY};font-size:13px;color:{INK}">'
            f'<div style="font-weight:bold;margin-bottom:4px">Yesterday</div>{"<br>".join(lines)}</td></tr>')


def render_html(date, days, recaps=None, ledger=None):
    """days = [(sport_key, picks.json dict)], recaps = [(sport_key, date, graded day)]."""
    body = "".join(_sport_section(k, d) for k, d in days)
    if not body:
        body = f'<tr><td style="padding:16px;color:{MUTED}">No games on the board today.</td></tr>'
    led = ""
    if ledger:
        rows = []
        for sport_key, _ in days:
            book = ledger.get(sport_key) or {}
            for sid, r in sorted(book.items(), key=lambda kv: -kv[1]["units"]):
                rows.append(f"{escape(sport_key)} · {escape(sid)}: {_rec(r)}")
        if rows:
            led = (f'<tr><td style="padding:12px 14px;font-size:12px;color:{MUTED}"><b>Source records</b><br>'
                   + "<br>".join(rows) + "</td></tr>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:{CREAM}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CREAM}"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;font-family:{FONT}">
<tr><td style="background:{NAVY};padding:18px 16px;color:#fff">
<div style="font:bold 20px {FONT};letter-spacing:.04em">🤖 MikeBot Daily Briefing</div>
<div style="font-size:13px;color:#c9d6ea;margin-top:2px">{escape(pretty_date(date))} · Bayside Sports Insights</div></td></tr>
{_recap_section(recaps)}
{body}
{led}
<tr><td style="padding:14px;font-size:11px;color:{MUTED};text-align:center">
✓ = explicit pick · ~ = inferred · score = T.A.G. agreement score (0-100)<br>
Sent by MikeBot for Bayside Sports Insights · For entertainment only, not betting advice. 21+, gamble responsibly (1-800-GAMBLER).</td></tr>
</table></td></tr></table></body></html>"""


def render_text(date, days, recaps=None):
    out = [f"MikeBot Daily Briefing — {pretty_date(date)}"]
    for sport_key, rdate, day in recaps or []:
        rec = summarize(day.get("picks", []))
        if rec["win"] + rec["loss"] + rec["push"]:
            out.append(f"Yesterday {sport_key}: {_rec(rec)}")
    for sport_key, day in days:
        games = day.get("games", [])
        if not games:
            continue
        out.append(f"\n{sport_key} — {len(games)} games, {len(day.get('picks', []))} picks")
        ranked = sorted(games, key=lambda g: -g.get("tier_score", 0))
        for g in ranked:
            if g.get("tier") in ("strong", "solid"):
                ps = [pick_label(p) + f" [{p['source_id']}]" for p in day["picks"] if p["game_id"] == g["game_id"]]
                out.append(f"• {g['matchup']} {g.get('game_time', '')} — {g['tier'].upper()} {g['tier_score']}: "
                           f"{g.get('consensus_side') or g.get('consensus_total', '')} | {'; '.join(ps)}")
        if not any(g.get("tier") in ("strong", "solid") for g in games):
            out.append("• No strong or solid signals yet.")
    out.append("\nFor entertainment only · not betting advice")
    return "\n".join(out)

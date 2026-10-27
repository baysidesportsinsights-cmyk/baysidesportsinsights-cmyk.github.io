"""MikeBot command line.

  python -m mikebot daily  [--date YYYY-MM-DD] [--sports NFL,NBA] [--send]
  python -m mikebot pull   [--date ...] [--sports ...] [--only pickdawgz,manual]
  python -m mikebot reflect [--date ...]          (defaults to yesterday)
  python -m mikebot jobs                          (everything MikeBot runs)
  python -m mikebot status                        (last runs + source records)
  python -m mikebot smoke  [--date ...]           (live dry run, writes nothing)
"""

import argparse
import os
import sys
import tempfile

from . import catalog, jobs, store
from .config import SPORTS, active_sports, shift_date, today_et
from .http import FetchError


def _sports(arg):
    if not arg:
        return active_sports()
    return [SPORTS[k.strip().upper()] for k in arg.split(",") if k.strip().upper() in SPORTS]


def cmd_daily(a):
    report, _, _ = jobs.daily(a.date or today_et(), sports=_sports(a.sports), send=a.send)
    return 1 if report["errors"] and not report["sports"] else 0


def cmd_pull(a):
    date = a.date or today_et()
    only = set(a.only.split(",")) if a.only else None
    failed = 0
    for sport in _sports(a.sports):
        try:
            day = jobs.pull(sport, date, only=only)
        except FetchError as e:
            print(f"[{sport.key}] pull failed: {e}")
            failed += 1
            continue
        if day["games"]:
            store.save_day(sport.key, date, day)
    return 1 if failed else 0


def cmd_reflect(a):
    date = a.date or shift_date(today_et(), -1)
    for sport in _sports(a.sports):
        try:
            day = jobs.reflect(sport, date)
        except FetchError as e:
            print(f"[{sport.key}] reflect failed: {e}")
            continue
        if day:
            store.save_day(sport.key, date, day)
    return 0


def cmd_jobs(a):
    for kind, title in (("code", "MikeBot code jobs"), ("claude", "Claude scheduled tasks MikeBot coordinates")):
        print(f"\n{title}")
        for j in catalog.by_kind(kind):
            print(f"  {j['id']:<20} {j['area']:<17} {j['when']:<34} {j['what']}")
    return 0


def cmd_status(a):
    runs = store.load_json(store.data_dir() / "runs.json", [])
    print("Last runs:")
    for r in runs[-5:]:
        print(f"  {r['at']} {r['job']} {r['date']} {r['sports']} errors={len(r['errors'])} {r.get('delivery', '')}")
    if not runs:
        print("  (none yet)")
    led = store.ledger()
    for sport_key in sorted(k for k in led if not k.startswith("_")):
        print(f"\n{sport_key} source records:")
        for sid, r in sorted(led[sport_key].items(), key=lambda kv: -kv[1]["units"]):
            print(f"  {sid:<16} {r['win']}-{r['loss']}-{r['push']}  {r['units']:+.2f}u")
    return 0


def cmd_smoke(a):
    """Live end-to-end run into a throwaway data dir. Fails only if ESPN is unreachable."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MIKEBOT_DATA_DIR"] = tmp
        date = a.date or today_et()
        report, html, text = jobs.daily(date, sports=_sports(a.sports), send=False)
        print("\n----- briefing (text) -----\n" + text)
        if a.html_out:
            with open(a.html_out, "w") as f:
                f.write(html)
    espn_down = [e for e in report["errors"] if "pull" in e]
    return 1 if espn_down and not report["sports"] else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="mikebot", description="MikeBot — the BSI umbrella agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("daily", cmd_daily), ("pull", cmd_pull), ("reflect", cmd_reflect),
                     ("jobs", cmd_jobs), ("status", cmd_status), ("smoke", cmd_smoke)):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        sp.add_argument("--date")
        sp.add_argument("--sports")
        if name == "daily":
            sp.add_argument("--send", action="store_true", help="email/Discord the briefing")
        if name == "pull":
            sp.add_argument("--only", help="comma-separated source ids")
        if name == "smoke":
            sp.add_argument("--html-out", help="also write the rendered briefing here")
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

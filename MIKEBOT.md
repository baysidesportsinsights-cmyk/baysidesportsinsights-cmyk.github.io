# MikeBot

MikeBot is the Bayside Sports Insights umbrella agent. It does two jobs:

1. **Runs the picks pipeline in code.** This is the T.A.G. design (Daily Prep → Daily Pull → Daily Reflection), done for any sport. It starts with **NFL and NBA**. MLB and NHL already work when the season comes back.
2. **Keeps the master list** of everything else that runs for BSI. That includes the Claude scheduled tasks for the FAB market, fantasy football and NFL DFS. Run `python -m mikebot jobs` to see it.

## The daily loop

| Step | What happens |
|------|--------------|
| **Daily Reflection** | It pulls yesterday's final scores from ESPN. Then it writes `settled_result` (win/loss/push) and `profit_units` on every pick, and updates `ledger.json`. The ledger holds each source's W-L and units, and how each consensus tier did. |
| **Daily Prep** | It gets today's schedule and market lines (spread, total, moneylines) from ESPN's public scoreboard, then builds `<SPORT>/<YYYY-MM-DD>/picks.json`. |
| **Daily Pull** | Every tout source runs, and the picks are merged. Each game gets a T.A.G. tier score: `agreement × 80 + min(sources, 8) × 2`. Strong is 75+, solid 55–74, split 35–54, weak under 35. |
| **Briefing** | A phone-friendly HTML email plus a text version for Discord. It covers yesterday's record, today's games by tier and each source's record. |

GitHub Actions runs it (`.github/workflows/mikebot-daily.yml`):
- **10:17 ET:** the full daily run, which sends the briefing.
- **17:47 ET:** a late re-pull for tonight's games. No email.

Run data goes to the **`mikebot-data`** branch, never to `main`, so it doesn't show up on the website. The layout matches the Drive convention: `NBA/2026-10-27/picks.json`.

> The repo is public, so the `mikebot-data` branch is readable by anyone on GitHub. To keep picks private, move MikeBot to a private repo. The code doesn't change.

## Sources

| id | How it works |
|----|--------------|
| `pickdawgz` | Finds each game's article on the sport's index page, then reads the pick ("I am backing the X"). |
| `pickswise` | Same approach: index page, then the per-game prediction pages. |
| `docsports` | Same approach: free-picks index, then the articles. |
| `manual` | `<SPORT>/<date>/manual.json`. This is the bridge for anything code can't scrape, like VSiN snippets, JS-rendered pages or YouTube. Mike or a Claude session drops picks here, and MikeBot scores and grades them like any other source. |

A source that fails never stops the run. The briefing just lists it as down. CI's **smoke** job runs every source live on each push, and its log shows which ones are healthy.

`manual.json` format:

```json
{"picks": [
  {"source_id": "vsin_peterson", "game": "BOS @ NY", "market": "spread",
   "team": "BOS", "line": -4.5, "odds": -110, "confidence": "confirmed",
   "notes": "Peterson: Celtics defense travels"}
]}
```

`market` is `moneyline`, `spread` or `total`. A total uses `"ou": "over"|"under"` and `"line": 221.5` instead of `team`. `game` is the `AWAY @ HOME` abbreviation pair from picks.json, or its `game_id`.

## Commands

```
python -m mikebot daily [--date YYYY-MM-DD] [--sports NFL,NBA] [--send]
python -m mikebot pull  [--only pickdawgz,manual]
python -m mikebot reflect [--date YYYY-MM-DD]     # default: yesterday
python -m mikebot status                          # last runs + source records
python -m mikebot jobs                            # everything MikeBot runs
python -m mikebot smoke                           # live dry run, writes nothing
python -m unittest discover -s tests
```

`MIKEBOT_DATA_DIR` sets the data folder (default `./data`). `MIKEBOT_SPORTS` sets the sports (default `NFL,NBA`).

## Turning on delivery

These go in the repo's Settings → Secrets and variables → Actions:

| Secret | Purpose |
|--------|---------|
| `MIKEBOT_SMTP_USER` | The Gmail address that sends the briefing |
| `MIKEBOT_SMTP_PASSWORD` | A Gmail **app password** for that account (not the normal password) |
| `MIKEBOT_EMAIL_TO` | Who gets the briefing (comma-separated) |
| `MIKEBOT_DISCORD_WEBHOOK` | Optional: a webhook for a sports-picks channel |

If none are set, the briefing still gets built and saved to `mikebot-data/briefings/<date>/`. It just isn't sent. The optional variable `MIKEBOT_SPORTS` (for example `NFL,NBA,NHL`) changes the sports.

## For Claude sessions acting as MikeBot

- To add picks from sources code can't reach, write `manual.json` (format above) and run `python -m mikebot pull --only manual`. In Actions, use **Run workflow → job: pull**.
- The Claude scheduled tasks (FAB, fantasy, DFS) stay as Claude tasks because they need Mike's Chrome session. `mikebot/catalog.py` lists them. Their full instructions live in the scheduled tasks, not in this public repo.
- For entertainment only. MikeBot never places bets or changes accounts.

"""Everything MikeBot is in charge of.

"code" jobs run from this package (GitHub Actions or any shell).
"claude" jobs are Claude scheduled tasks on the BSI account. They need Mike's
Chrome session (TCGplayer, ESPN/Yahoo fantasy) so they stay as Claude tasks;
MikeBot tracks them so there's one list of what runs when. Their full prompts
live in the scheduled tasks themselves, not in this public repo.
"""

JOBS = [
    # --- code jobs (this package) ---
    {"id": "picks-daily", "kind": "code", "area": "Picks", "when": "daily 10:17 ET",
     "what": "Grade yesterday (Daily Reflection), build today's board from ESPN + tout sources "
             "(Daily Prep + Daily Pull), score T.A.G. tiers, send the briefing.",
     "run": "python -m mikebot daily --send"},
    {"id": "picks-late", "kind": "code", "area": "Picks", "when": "daily 17:47 ET",
     "what": "Re-pull tout sources for tonight's games (late articles), rescore. No email.",
     "run": "python -m mikebot pull"},
    {"id": "smoke", "kind": "code", "area": "Health", "when": "every push",
     "what": "Unit tests plus a live dry run of every data source; shows which sources are healthy.",
     "run": "python -m mikebot smoke"},
    # --- Claude scheduled tasks MikeBot coordinates with ---
    {"id": "fab-command-center", "kind": "claude", "area": "FAB / TCGplayer", "when": "daily 7:49 ET + 16:04 ET",
     "what": "Command Center refresh: orders, inventory, market, meta; builds Mike's Market Minute "
             "(Discord via the Drive poster)."},
    {"id": "fab-breaking-news", "kind": "claude", "area": "FAB / TCGplayer", "when": "hourly 10:49-23:49 ET, 3-hourly overnight",
     "what": "Spike watch: confirmed buyouts and top seller of the day to Discord."},
    {"id": "fantasy-pulse", "kind": "claude", "area": "Fantasy football", "when": "daily ~8:30 ET",
     "what": "League activity, injuries and flags for both fantasy teams."},
    {"id": "fantasy-weekly", "kind": "claude", "area": "Fantasy football", "when": "Tue ~10:00 ET",
     "what": "Season Command Center weekly refresh, trade finder, review email."},
    {"id": "fantasy-executor", "kind": "claude", "area": "Fantasy football", "when": "hourly",
     "what": "Executes roster moves Mike approved on the Command Center."},
    {"id": "fantasy-inactives", "kind": "claude", "area": "Fantasy football", "when": "Sun ~11:45 ET",
     "what": "Swaps OUT/Doubtful starters before the 1:00 games."},
    {"id": "fantasy-lock-check", "kind": "claude", "area": "Fantasy football", "when": "Mon + Thu ~19:30 ET",
     "what": "Same check before the national night game."},
    {"id": "dfs-retro", "kind": "claude", "area": "NFL DFS", "when": "Tue 8:55 ET",
     "what": "Weekly DraftKings slate retrospective, ledger row and one action."},
]


def by_kind(kind):
    return [j for j in JOBS if j["kind"] == kind]

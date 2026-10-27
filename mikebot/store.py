"""On-disk layout: <data>/<SPORT>/<YYYY-MM-DD>/picks.json (one folder per day,
matching the Drive convention), plus <data>/ledger.json and <data>/runs.json."""

import json

from .config import data_dir


def day_dir(sport_key, date):
    return data_dir() / sport_key / date


def picks_path(sport_key, date):
    return day_dir(sport_key, date) / "picks.json"


def load_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    return path


def load_day(sport_key, date):
    return load_json(picks_path(sport_key, date))


def save_day(sport_key, date, day):
    return save_json(picks_path(sport_key, date), day)


def ledger():
    return load_json(data_dir() / "ledger.json", {})


def save_ledger(obj):
    return save_json(data_dir() / "ledger.json", obj)


def log_run(entry, keep=200):
    path = data_dir() / "runs.json"
    runs = load_json(path, [])
    runs.append(entry)
    save_json(path, runs[-keep:])

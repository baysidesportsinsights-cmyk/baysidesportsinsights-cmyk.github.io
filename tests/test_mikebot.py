import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mikebot import briefing, espn, jobs, store
from mikebot.config import SPORTS
from mikebot.grading import grade_day, grade_pick, update_ledger
from mikebot.scoring import score_game
from mikebot.sources import SOURCES, ManualSource, link_matches
from mikebot.sources.extract import extract_picks, html_to_text, parse_selection

FIX = Path(__file__).parent / "fixtures"
NBA = SPORTS["NBA"]


def games():
    return espn.parse_scoreboard(json.loads((FIX / "nba_scoreboard.json").read_text()), NBA)


def pick(src, gid, market, team=None, line=None, ou=None, conf="confirmed"):
    return {"source_id": src, "game_id": gid, "market": market, "side": {"team": team, "line": line, "ou": ou},
            "odds": None, "units": 1, "confidence": conf, "settled_result": None}


class EspnTest(unittest.TestCase):
    def test_parse(self):
        g = {x["matchup"]: x for x in games()}
        self.assertEqual(set(g), {"BOS @ NY", "GS @ LAL", "ORL @ MIA"})
        bos = g["BOS @ NY"]
        self.assertEqual(bos["odds"]["favorite"], "BOS")
        self.assertEqual(bos["odds"]["home_spread"], 4.5)
        self.assertEqual(bos["odds"]["total"], 221.5)
        self.assertEqual((bos["odds"]["ml_home"], bos["odds"]["ml_away"]), (160, -190))
        self.assertEqual(bos["game_time"], "7:30p")
        self.assertEqual(bos["away"]["record"], "3-0")
        gs = g["GS @ LAL"]
        self.assertEqual(gs["odds"]["home_spread"], 0)
        self.assertEqual((gs["odds"]["ml_home"], gs["odds"]["ml_away"]), (-105, -115))
        self.assertEqual(gs["odds"]["total"], 228.5)
        mia = g["ORL @ MIA"]
        self.assertTrue(mia["completed"])
        self.assertEqual((mia["home"]["score"], mia["away"]["score"]), (104, 110))


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.g = next(x for x in games() if x["matchup"] == "BOS @ NY")

    def test_article(self):
        text = html_to_text((FIX / "pickdawgz_article.html").read_text())
        self.assertNotIn("backing the Knicks", text)  # script contents dropped
        picks = extract_picks(text, self.g)
        got = {(p["market"], p["side"]["team"], p["side"]["line"], p["side"]["ou"]) for p in picks}
        self.assertEqual(got, {("spread", "BOS", -4.5, None), ("total", None, 221.5, "under")})
        self.assertTrue(all(p["confidence"] == "confirmed" for p in picks))

    def test_selections(self):
        cases = {
            "Knicks ML": ("moneyline", "NY", None),
            "New York Knicks +4.5": ("spread", "NY", 4.5),
            "Celtics (-190)": ("moneyline", "BOS", None),
            "the Celtics to win": ("moneyline", "BOS", None),
            "Over 221.5": ("total", None, 221.5),
            "Boston": ("moneyline", "BOS", None),
        }
        for sel, (market, team, line) in cases.items():
            m, side = parse_selection(sel, self.g)
            self.assertEqual((m, side["team"], side["line"]), (market, team, line), sel)
        self.assertIsNone(parse_selection("the home dog", self.g))

    def test_two_selections_in_one_pick(self):
        # Doc's Sports phrasing seen live on 2026-10-27
        picks = extract_picks("Pick: Take New York and under the total points.", self.g)
        got = {(p["market"], p["side"]["team"], p["side"]["ou"]) for p in picks}
        self.assertEqual(got, {("moneyline", "NY", None), ("total", None, "under")})

    def test_inferred_only_when_no_confirmed(self):
        picks = extract_picks("We lean the Knicks at home tonight.", self.g)
        self.assertEqual([(p["side"]["team"], p["confidence"]) for p in picks], [("NY", "inferred")])


class LinkTest(unittest.TestCase):
    def test_link_matching(self):
        g = {x["matchup"]: x for x in games()}
        idx = (FIX / "pickdawgz_index.html").read_text()
        import re
        links = re.findall(r'href="([^"]+)"', idx)
        bos = [u for u in links if link_matches(u, g["BOS @ NY"], "2026-10-27")]
        self.assertEqual(len(bos), 1)
        self.assertIn("celtics", bos[0])
        self.assertEqual([u for u in links if link_matches(u, g["ORL @ MIA"], "2026-10-27")], [])  # stale date
        self.assertEqual(len([u for u in links if link_matches(u, g["GS @ LAL"], "2026-10-27")]), 1)


class LiveFormatTest(unittest.TestCase):
    def test_pickswise_game_links(self):
        import re
        src = next(x for x in SOURCES if x.id == "pickswise")
        g = {x["matchup"]: x for x in games()}
        page = ('<a href="/nba/games/boston-celtics-new-york-knicks-nba-2026-10-27-1930/picks/">p</a>'
                '<a href="/nba/games/boston-celtics-new-york-knicks-nba-2026-10-27-1930/">g</a>'
                '<a href="/nba/news/nba-best-bets-today-october-27-picks-predictions/">n</a>')
        links = re.findall(src.link_re.format(slug="nba"), page)
        self.assertEqual(links, ["/nba/games/boston-celtics-new-york-knicks-nba-2026-10-27-1930/picks/"])
        self.assertTrue(link_matches(links[0], g["BOS @ NY"], "2026-10-27"))

    def test_docsports_bare_team_is_spread(self):
        from mikebot.sources import is_bare_team
        g = next(x for x in games() if x["matchup"] == "BOS @ NY")
        p = extract_picks("Pick: Take Boston", g)[0]
        self.assertTrue(is_bare_team(p))
        self.assertFalse(is_bare_team(extract_picks("Pick: Celtics ML", g)[0]))
        self.assertEqual(next(x for x in SOURCES if x.id == "docsports").bare_team, "spread")


class ScoringTest(unittest.TestCase):
    def test_tiers(self):
        g = games()[0]
        gid = g["game_id"]
        self.assertEqual(score_game(g, [])["tier"], "insufficient")
        one = score_game(g, [pick("a", gid, "spread", "BOS", -4.5)])
        self.assertEqual((one["tier"], one["tier_score"]), ("strong", 82))
        agree = [pick("a", gid, "spread", "BOS"), pick("b", gid, "moneyline", "BOS"), pick("c", gid, "spread", "NY")]
        s = score_game(g, agree)
        self.assertEqual(s["consensus_side"], "BOS")
        self.assertEqual(s["tier_score"], round(2 / 3 * 80 + 6))
        self.assertEqual(s["tier"], "solid")
        even = score_game(g, [pick("a", gid, "spread", "BOS"), pick("b", gid, "spread", "NY")])
        self.assertIsNone(even["consensus_side"])
        self.assertEqual(even["tier"], "split")
        tot = score_game(g, [pick("a", gid, "total", ou="under", line=221.5)])
        self.assertEqual((tot["consensus_total"], tot["tier"]), ("under", "strong"))


class GradingTest(unittest.TestCase):
    def test_grades(self):
        mia = next(x for x in games() if x["matchup"] == "ORL @ MIA")  # ORL 110 - MIA 104, MIA -2.5, 214.5
        gid = mia["game_id"]
        self.assertEqual(grade_pick(pick("a", gid, "moneyline", "ORL"), mia), "win")
        self.assertEqual(grade_pick(pick("a", gid, "spread", "MIA"), mia), "loss")    # line from market
        self.assertEqual(grade_pick(pick("a", gid, "spread", "MIA", 6), mia), "push")
        self.assertEqual(grade_pick(pick("a", gid, "spread", "ORL", 2.5), mia), "win")
        self.assertEqual(grade_pick(pick("a", gid, "total", ou="over"), mia), "loss")  # 214 < 214.5
        self.assertEqual(grade_pick(pick("a", gid, "total", ou="under", line=214), mia), "push")
        pre = games()[0]
        self.assertIsNone(grade_pick(pick("a", pre["game_id"], "moneyline", "BOS"), pre))

    def test_grade_day_and_ledger(self):
        g = games()
        mia = next(x for x in g if x["matchup"] == "ORL @ MIA")
        day = {"games": [mia], "picks": [pick("a", mia["game_id"], "spread", "ORL", 2.5),
                                         pick("b", mia["game_id"], "moneyline", "MIA")]}
        mia.update(score_game(mia, day["picks"]))
        self.assertEqual(grade_day(day), {"graded": 2, "pending": 0})
        self.assertAlmostEqual(day["picks"][0]["profit_units"], 0.909, places=3)
        led = update_ledger({}, "NBA", "2026-10-27", day)
        self.assertEqual(led["NBA"]["a"]["win"], 1)
        self.assertEqual(led["NBA"]["b"]["loss"], 1)
        again = update_ledger(led, "NBA", "2026-10-27", day)  # idempotent per day
        self.assertEqual(again["NBA"]["a"]["win"], 1)


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MIKEBOT_DATA_DIR"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("MIKEBOT_DATA_DIR", None)

    def fake_fetch(self, url, **kw):
        if url.rstrip("/").endswith("pickdawgz.com/nba-picks"):
            return (FIX / "pickdawgz_index.html").read_text()
        if "boston-celtics-vs-new-york-knicks" in url:
            return (FIX / "pickdawgz_article.html").read_text()
        from mikebot.http import FetchError
        raise FetchError(f"404 {url}")

    def test_daily_end_to_end(self):
        sb = json.loads((FIX / "nba_scoreboard.json").read_text())
        manual = Path(self.tmp.name) / "NBA" / "2026-10-27" / "manual.json"
        manual.parent.mkdir(parents=True)
        manual.write_text(json.dumps({"picks": [
            {"source_id": "vsin_peterson", "game": "BOS @ NY", "market": "moneyline", "team": "BOS"},
            {"source_id": "vsin_peterson", "game": "XXX @ YYY", "market": "moneyline", "team": "XXX"}]}))
        with mock.patch("mikebot.espn.fetch_json", return_value=sb), \
             mock.patch("mikebot.sources.fetch", side_effect=self.fake_fetch):
            report, html, text = jobs.daily("2026-10-27", sports=[NBA], send=False, log=lambda *_: None)
        self.assertEqual(report["sports"]["NBA"]["games"], 3)
        day = store.load_day("NBA", "2026-10-27")
        bos = next(g for g in day["games"] if g["matchup"] == "BOS @ NY")
        self.assertEqual((bos["consensus_side"], bos["tier"], bos["source_count"]), ("BOS", "strong", 2))
        runs = {r["source_id"]: r for r in day["source_runs"]}
        self.assertEqual(runs["pickdawgz"]["status"], "ok")
        self.assertIn("1 unmatched", runs["manual"]["note"])
        self.assertIn("BOS @ NY", html)
        self.assertIn("STRONG", text)
        self.assertTrue((Path(self.tmp.name) / "briefings" / "2026-10-27" / "briefing.html").exists())

        # next morning: reflection grades yesterday from the final scoreboard
        final = json.loads(json.dumps(sb))
        ev = final["events"][0]
        ev["status"]["type"].update(state="post", completed=True)
        ev["competitions"][0]["competitors"][0]["score"] = "100"  # NY
        ev["competitions"][0]["competitors"][1]["score"] = "112"  # BOS
        with mock.patch("mikebot.espn.fetch_json", side_effect=[final, {"events": []}]), \
             mock.patch("mikebot.sources.fetch", side_effect=self.fake_fetch):
            report, html, text = jobs.daily("2026-10-28", sports=[NBA], send=False, log=lambda *_: None)
        graded = store.load_day("NBA", "2026-10-27")
        res = {(p["source_id"], p["market"]): p["settled_result"] for p in graded["picks"]}
        self.assertEqual(res[("pickdawgz", "spread")], "win")       # BOS -4.5 won by 12
        self.assertEqual(res[("pickdawgz", "total")], "win")        # 212 under 221.5
        self.assertEqual(res[("vsin_peterson", "moneyline")], "win")
        led = store.ledger()
        self.assertEqual(led["NBA"]["pickdawgz"]["win"], 2)
        self.assertIn("Yesterday NBA: 3-0", text)


class BriefingTest(unittest.TestCase):
    def test_render_empty(self):
        html = briefing.render_html("2026-10-27", [])
        self.assertIn("No games on the board today", html)
        self.assertIn("Tuesday, October 27, 2026", briefing.subject("2026-10-27"))


class SourcesTest(unittest.TestCase):
    def test_registry(self):
        ids = [s.id for s in SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIsInstance(SOURCES[-1], ManualSource)


if __name__ == "__main__":
    unittest.main()

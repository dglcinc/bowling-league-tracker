"""
Smoke tests for chat_tools.py against the live SQLite DB.

Each tool is invoked with realistic args and asserted to return a non-empty
result. The fixture season is the most recently entered one, and the fixture
bowler is the first one available on its roster — so the tests stay green
regardless of which DB snapshot the developer is pointed at.

Run with either:
    python3 -m unittest tests.test_chat_tools
    python3 -m pytest tests/test_chat_tools.py
"""

import os
import sys
import unittest

# Make sibling modules importable when run from the project root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, Bowler, Roster, Season
import chat_tools


class ChatToolsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

        # Pick a season with entered data to exercise season-scoped tools.
        seasons = chat_tools.list_seasons()
        if not seasons:
            raise unittest.SkipTest("No seasons with entered data — DB is empty.")

        # Prefer 2025-2026 if present, else the most recent entered season.
        match = next((s for s in seasons if s['name'] == '2025-2026'), None)
        cls.season_id = (match or seasons[-1])['id']
        cls.season_name = (match or seasons[-1])['name']

        # Find a bowler with career data in this season — Lewis if rostered, else
        # the first roster entry's bowler.
        lewis = (Bowler.query
                 .filter(Bowler.last_name.ilike('lewis'))
                 .first())
        rostered = (Roster.query
                    .filter_by(season_id=cls.season_id)
                    .first())
        if lewis and Roster.query.filter_by(
                bowler_id=lewis.id, season_id=cls.season_id).first():
            cls.bowler_id = lewis.id
        elif rostered:
            cls.bowler_id = rostered.bowler_id
        else:
            raise unittest.SkipTest("No rostered bowler in the chosen season.")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    # ---- catalog wiring ----

    def test_tool_schemas_well_formed(self):
        names = {s['function']['name'] for s in chat_tools.TOOL_SCHEMAS}
        self.assertEqual(names, set(chat_tools._DISPATCH.keys()))
        for s in chat_tools.TOOL_SCHEMAS:
            self.assertEqual(s['type'], 'function')
            f = s['function']
            self.assertIn('description', f)
            self.assertIn('parameters', f)
            self.assertEqual(f['parameters']['type'], 'object')

    def test_dispatch_unknown_raises(self):
        with self.assertRaises(KeyError):
            chat_tools.dispatch('nope', {})

    def test_dispatch_routes_by_name(self):
        result = chat_tools.dispatch('list_seasons', {})
        self.assertTrue(len(result) > 0)

    # ---- per-tool smoke tests ----

    def test_list_seasons(self):
        rows = chat_tools.list_seasons()
        self.assertGreater(len(rows), 0)
        for r in rows:
            self.assertIn('id', r)
            self.assertIn('name', r)
            self.assertIn('venue', r)

    def test_list_bowlers_substring(self):
        rows = chat_tools.list_bowlers(last_name_substring='e')
        self.assertGreater(len(rows), 0)
        self.assertTrue(all('e' in (r['last_name'] or '').lower() for r in rows))

    def test_list_bowlers_by_season(self):
        rows = chat_tools.list_bowlers(season_id=self.season_id)
        self.assertGreater(len(rows), 0)

    def test_bowler_career_stats(self):
        rows = chat_tools.bowler_career_stats(self.bowler_id)
        self.assertGreater(len(rows), 0)
        self.assertIn('avg', rows[0])

    def test_bowler_season_stats(self):
        s = chat_tools.bowler_season_stats(self.bowler_id, self.season_id)
        self.assertEqual(s['bowler_id'], self.bowler_id)
        self.assertEqual(s['season_id'], self.season_id)
        self.assertIn('running_avg', s)
        self.assertNotIn('weekly_stats', s)

    def test_season_leaders(self):
        rows = chat_tools.season_leaders(self.season_id)
        self.assertGreater(len(rows), 0)
        self.assertIn('average', rows[0])

    def test_season_leaders_top10(self):
        rows = chat_tools.season_leaders(self.season_id, top10=True)
        # top10 is "top-10 distinct averages with all ties" — could be ≥ 10, ≤ all.
        self.assertGreater(len(rows), 0)

    def test_all_time_records(self):
        out = chat_tools.all_time_records()
        for cat in ('hg_scratch', 'hs_scratch', 'hg_hcp', 'hs_hcp', 'avg'):
            self.assertIn(cat, out)
        # At least one category must be populated against any non-empty DB.
        self.assertTrue(any(out[c] for c in out))

    def test_all_time_records_filtered_category(self):
        out = chat_tools.all_time_records(category='hg_scratch', limit=5)
        self.assertEqual(set(out.keys()), {'hg_scratch'})
        self.assertLessEqual(len(out['hg_scratch']), 5)

    def test_most_improved(self):
        rows = chat_tools.most_improved()
        # Most_improved requires ≥ 2 seasons of data per bowler. May be empty
        # on a brand-new DB, so this just asserts the tool runs and returns a list.
        self.assertIsInstance(rows, list)

    def test_fun_stats(self):
        out = chat_tools.fun_stats()
        for key in ('worst_avg', 'most_season_games', 'most_career_games',
                    'most_200', 'lowest_games', 'min_qualified',
                    'tournament_placements_per_type',
                    'tournament_placements_overall'):
            self.assertIn(key, out)
        self.assertTrue(out['most_career_games'])

    def test_tournament_winners(self):
        rows = chat_tools.tournament_winners()
        self.assertIsInstance(rows, list)
        # Most DBs have at least one season with tournament data; if not, the
        # list is empty but the tool still ran.
        if rows:
            self.assertIn('season', rows[0])
            self.assertIn('club_by_place', rows[0])

    def test_team_standings(self):
        rows = chat_tools.team_standings(self.season_id)
        self.assertGreater(len(rows), 0)
        self.assertIn('points', rows[0])
        self.assertIn('team', rows[0])

    def test_weekly_prizes(self):
        # Find the first week with entries in the test season.
        from models import MatchupEntry
        wk = (db.session.query(MatchupEntry.week_num)
              .filter_by(season_id=self.season_id, is_blind=False)
              .order_by(MatchupEntry.week_num).first())
        if not wk:
            self.skipTest("No entered weeks in the test season.")
        prizes = chat_tools.weekly_prizes(self.season_id, wk[0])
        self.assertIsNotNone(prizes)
        for cat in ('hg_scratch', 'hg_hcp', 'hs_scratch', 'hs_hcp'):
            self.assertIn(cat, prizes)


if __name__ == '__main__':
    unittest.main()

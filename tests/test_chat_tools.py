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

        # Pick a season to exercise season-scoped tools. Prefer 2025-2026
        # if present, else the most recent season by start_date.
        season = (Season.query.filter_by(name='2025-2026').first()
                  or Season.query.order_by(Season.start_date.desc()).first())
        if season is None:
            raise unittest.SkipTest("No seasons in DB.")
        cls.season_id = season.id
        cls.season_name = season.name

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
        result = chat_tools.dispatch('query_db', {'sql': 'SELECT 1 AS one'})
        self.assertEqual(result['rows'], [{'one': 1}])

    # ---- per-tool smoke tests ----

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

    def test_query_db_basic_select(self):
        out = chat_tools.query_db(sql='SELECT COUNT(*) AS n FROM bowlers')
        self.assertNotIn('error', out)
        self.assertEqual(out['row_count'], 1)
        self.assertGreater(out['rows'][0]['n'], 0)

    def test_query_db_with_named_params(self):
        out = chat_tools.query_db(
            sql='SELECT id, last_name FROM bowlers WHERE id = :bid',
            params={'bid': self.bowler_id},
        )
        self.assertEqual(out['row_count'], 1)
        self.assertEqual(out['rows'][0]['id'], self.bowler_id)

    def test_query_db_rejects_mutation(self):
        for sql in (
            'DELETE FROM bowlers',
            'UPDATE bowlers SET last_name = "x"',
            'DROP TABLE bowlers',
            'INSERT INTO bowlers VALUES (1)',
            'SELECT 1; DROP TABLE bowlers',
            'WITH x AS (UPDATE bowlers SET last_name="x") SELECT * FROM x',
        ):
            out = chat_tools.query_db(sql=sql)
            self.assertIn('error', out, f'should reject: {sql!r}')

    def test_query_db_rejects_forbidden_tables(self):
        out = chat_tools.query_db(sql='SELECT * FROM user_account')
        self.assertIn('error', out)
        self.assertIn('user_account', out['error'])

    def test_query_db_caps_at_200_rows(self):
        out = chat_tools.query_db(sql='SELECT id FROM bowlers')
        self.assertLessEqual(out['row_count'], 200)
        # If the DB has >200 bowlers (currently ~280), truncated should be True.
        from models import Bowler
        if Bowler.query.count() > 200:
            self.assertTrue(out['truncated'])

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

# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright David Lewis
"""
Team game totals when the lineup changes in the middle of a series.

A blind that covers only some games must score in those games: a bowler who
leaves after game 2 is replaced by a blind in game 3, and a late arrival is
covered by a blind in the games he missed.

The tests build their own season in an empty scratch database, so they never
touch league data. Run this module on its own:
    python3 -m unittest tests.test_blind_slots
"""

import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

_SCRATCH = tempfile.mkdtemp(prefix='bowling-test-')
os.environ['BOWLING_DB_DIR'] = _SCRATCH

from app import create_app
from models import (db, Bowler, MatchupEntry, Roster, ScheduleEntry, Season,
                    Team, Week)
from calculations import (entry_game_slots, get_position_night_breakdown,
                          score_matchup, score_position_night)

HCP = 50          # every test bowler carries this prior handicap
BLIND = 125 + 60  # blind scratch + blind handicap, per game


class BlindSlotsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        if _SCRATCH not in cls.app.config['SQLALCHEMY_DATABASE_URI']:
            raise unittest.SkipTest('Not on the scratch database; run this module alone.')
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

        season = Season(name='test-blind-slots', start_date=date(2000, 9, 1),
                        num_weeks=22, is_active=False)
        db.session.add(season)
        db.session.flush()
        cls.sid = season.id
        cls.season = season
        cls.t1 = Team(season_id=cls.sid, number=1, name='Team 1')
        cls.t2 = Team(season_id=cls.sid, number=2, name='Team 2')
        db.session.add_all([cls.t1, cls.t2])
        db.session.flush()

        cls.bowlers = {}
        for team in (cls.t1, cls.t2):
            ids = []
            for n in range(3):
                b = Bowler(last_name=f'Test{team.number}{n}', first_name='T')
                db.session.add(b)
                db.session.flush()
                db.session.add(Roster(bowler_id=b.id, season_id=cls.sid,
                                      team_id=team.id, active=True,
                                      prior_handicap=HCP))
                ids.append(b.id)
            cls.bowlers[team.id] = ids
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.ctx.pop()

    def setUp(self):
        # Each test starts with no games bowled, so every bowler is under six
        # games and bowls on the prior handicap.
        MatchupEntry.query.filter_by(season_id=self.sid).delete()
        db.session.commit()

    def _week(self, week_num, position_night=False, matchups=(1,)):
        db.session.add(Week(season_id=self.sid, week_num=week_num,
                            date=date(2000, 9, 1),
                            is_position_night=position_night))
        for m in matchups:
            db.session.add(ScheduleEntry(season_id=self.sid, week_num=week_num,
                                         matchup_num=m, team1_id=self.t1.id,
                                         team2_id=self.t2.id))

    def _row(self, week_num, team, games, bowler=None, matchup=1):
        db.session.add(MatchupEntry(
            season_id=self.sid, week_num=week_num, matchup_num=matchup,
            team_id=team.id, bowler_id=bowler, is_blind=bowler is None,
            lane_side='A' if team is self.t1 else 'B',
            game1=games[0], game2=games[1], game3=games[2]))

    def test_slots_helper(self):
        blind = MatchupEntry(is_blind=True, game1=None, game2=None, game3=125)
        self.assertEqual(entry_game_slots(blind, self.season), [None, None, 125])
        empty = MatchupEntry(is_blind=True)
        self.assertEqual(entry_game_slots(empty, self.season), [125, 125, 125])
        bowler = MatchupEntry(is_blind=False, game1=None, game2=150, game3=160)
        self.assertEqual(entry_game_slots(bowler, self.season), [None, 150, 160])

    def test_bowler_leaves_after_game_two(self):
        wk = 1
        self._week(wk)
        a, b, c = self.bowlers[self.t1.id]
        x, y, z = self.bowlers[self.t2.id]
        for bid in (a, b, c):
            self._row(wk, self.t1, (140, 140, 140), bid)
        self._row(wk, self.t2, (140, 140, 140), x)
        self._row(wk, self.t2, (140, 140, 140), y)
        self._row(wk, self.t2, (150, 150, None), z)   # left after game 2
        self._row(wk, self.t2, (None, None, 125))     # blind bowls game 3
        db.session.commit()

        r = score_matchup(self.sid, wk, 1)
        t1 = 3 * (140 + HCP)
        self.assertEqual(
            [(g['team1_total'], g['team2_total']) for g in r['game_detail']],
            [(t1, t1 + 10), (t1, t1 + 10), (t1, 2 * (140 + HCP) + BLIND)])
        # Team 2 takes games 1 and 2 and the series; team 1 takes game 3.
        self.assertEqual((r[self.t1.id], r[self.t2.id]), (1, 3))

    def test_blind_covers_late_arrival(self):
        wk = 2
        self._week(wk)
        a, b, c = self.bowlers[self.t1.id]
        x, y, z = self.bowlers[self.t2.id]
        for bid in (a, b, c):
            self._row(wk, self.t1, (140, 140, 140), bid)
        self._row(wk, self.t2, (140, 140, 140), x)
        self._row(wk, self.t2, (140, 140, 140), y)
        self._row(wk, self.t2, (125, 125, None))      # blind bowls games 1-2
        self._row(wk, self.t2, (None, None, 160), z)  # arrived for game 3
        db.session.commit()

        r = score_matchup(self.sid, wk, 1)
        t1 = 3 * (140 + HCP)
        both = 2 * (140 + HCP)
        self.assertEqual(
            [(g['team1_total'], g['team2_total']) for g in r['game_detail']],
            [(t1, both + BLIND), (t1, both + BLIND), (t1, both + 160 + HCP)])
        self.assertEqual((r[self.t1.id], r[self.t2.id]), (2, 2))

    def test_position_night_scores_blind_by_slot(self):
        wk = 11
        self._week(wk, position_night=True, matchups=(1, 2))
        a, b, _ = self.bowlers[self.t1.id]
        x, y, _ = self.bowlers[self.t2.id]
        self._row(wk, self.t1, (140, 140, 140), a)
        self._row(wk, self.t1, (140, 140, 140), b)
        self._row(wk, self.t2, (140, 140, 140), x)
        self._row(wk, self.t2, (150, 150, None), y)
        self._row(wk, self.t2, (None, None, 125))
        db.session.commit()

        both = 2 * (140 + HCP)
        bd = get_position_night_breakdown(self.sid, wk, 1)
        self.assertEqual([(g['t1'], g['t2']) for g in bd['games']],
                         [(both, both + 10), (both, both + 10),
                          (both, 140 + HCP + BLIND)])
        pts = score_position_night(self.sid, wk)
        self.assertEqual((pts[self.t1.id], pts[self.t2.id]), (2, 6))


if __name__ == '__main__':
    unittest.main()

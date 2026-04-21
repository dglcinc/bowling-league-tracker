"""
One-time script: convert Josh Wiener's Harry Russell write-in entry to his bowler record.

Run on the production server:
  cd ~/bowling-league-tracker && python fix_wiener.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Season, Week, TournamentEntry, Bowler

with app.app_context():
    season = Season.query.filter_by(name='2025-2026').first()
    if not season:
        print('ERROR: 2025-2026 season not found')
        sys.exit(1)

    week = Week.query.filter_by(season_id=season.id, tournament_type='indiv_scratch').first()
    if not week:
        print('ERROR: Harry Russell week not found')
        sys.exit(1)
    print(f'Harry Russell: season {season.id}, week {week.week_num}')

    # Find write-in entry
    write_ins = TournamentEntry.query.filter_by(
        season_id=season.id, week_num=week.week_num, bowler_id=None
    ).all()
    print(f'Write-in entries: {[(e.guest_name, e.game1, e.game2, e.game3, e.game4, e.game5) for e in write_ins]}')

    # Find Josh Wiener in bowlers
    wiener = Bowler.query.filter(
        Bowler.last_name.ilike('%wiener%')
    ).all()
    print(f'Bowlers matching Wiener: {[(b.id, b.first_name, b.last_name) for b in wiener]}')

    if len(wiener) != 1:
        print('Ambiguous or no match — fix manually')
        sys.exit(1)

    target_entry = next((e for e in write_ins if 'wiener' in (e.guest_name or '').lower()), None)
    if not target_entry:
        print('No write-in entry with "Wiener" found — check guest_name values above')
        sys.exit(1)

    print(f'\nWill update entry guest_name="{target_entry.guest_name}" → bowler_id={wiener[0].id}')
    confirm = input('Proceed? [y/N] ')
    if confirm.strip().lower() != 'y':
        print('Aborted')
        sys.exit(0)

    target_entry.bowler_id = wiener[0].id
    target_entry.guest_name = None
    db.session.commit()
    print('Done.')

"""
Import bowler roster from end-of-season XLS into the active season.

Usage (run on your Mac from the bowling-league-tracker directory):
    python seed_from_xls.py "/path/to/scoring 2025-2026 - Week 22.xlsx"

What it does:
- Reads bowler names, teams, nicknames, emails from 'wkly alpha' sheet
- Uses current-season handicap (col J) as prior_handicap for the new season
- Marks active/inactive from col P
- Skips non-bowler rows automatically
- Safe to re-run: checks for existing bowlers by last name before inserting
"""

import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl")
    sys.exit(1)

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

xls_path = Path(sys.argv[1])
if not xls_path.exists():
    print(f"ERROR: File not found: {xls_path}")
    sys.exit(1)

from app import create_app
from models import db, Bowler, Roster, Season, Team

SKIP_NAMES = {'6 games worksheet', 'weekly highs'}

app = create_app()

print(f"Loading: {xls_path.name}")
wb = openpyxl.load_workbook(xls_path, data_only=True)
ws = wb['wkly alpha']

with app.app_context():
    season = Season.query.filter_by(is_active=True).first()
    if not season:
        print("ERROR: No active season found. Create a season in the app first.")
        sys.exit(1)

    print(f"Importing into season: {season.name}")

    teams = Team.query.filter_by(season_id=season.id).all()
    team_map = {t.number: t for t in teams}

    added = updated = skipped = 0

    for row in ws.iter_rows(min_row=8, max_row=70, min_col=1, max_col=21, values_only=True):
        last_name = row[0]
        if not last_name or not isinstance(last_name, str):
            continue
        if last_name.strip().lower() in SKIP_NAMES:
            continue

        first_name  = (row[1] or '').strip() or None
        nickname    = (row[2] or '').strip() or None
        team_num    = row[3]
        curr_hcp    = int(row[9]) if row[9] else 0   # col J → prior hcp for next season
        active      = str(row[15] or '').strip().lower() == 'yes'
        email       = (row[19] or '').strip() or None

        if team_num not in team_map:
            print(f"  SKIP (unknown team {team_num}): {last_name}")
            skipped += 1
            continue

        # Check if bowler already exists (by last name — safe for this league)
        bowler = Bowler.query.filter_by(last_name=last_name.strip()).first()
        if not bowler:
            bowler = Bowler(
                last_name=last_name.strip(),
                first_name=first_name,
                nickname=nickname,
                email=email,
            )
            db.session.add(bowler)
            db.session.flush()
            added += 1
            action = 'ADD'
        else:
            # Update email/nickname if missing
            if not bowler.nickname and nickname:
                bowler.nickname = nickname
            if not bowler.email and email:
                bowler.email = email
            updated += 1
            action = 'UPD'

        # Upsert roster entry
        roster = Roster.query.filter_by(
            bowler_id=bowler.id, season_id=season.id
        ).first()
        if not roster:
            roster = Roster(
                bowler_id=bowler.id,
                season_id=season.id,
                team_id=team_map[team_num].id,
                active=active,
                prior_handicap=curr_hcp,
                joined_week=1,
            )
            db.session.add(roster)
        else:
            roster.team_id = team_map[team_num].id
            roster.active = active
            roster.prior_handicap = curr_hcp

        flag = '✓' if active else '–'
        print(f"  [{action}] {flag} {last_name:<16} {(first_name or ''):<12} "
              f"T{team_num} ({team_map[team_num].name:<10}) hcp={curr_hcp:>3}")

    db.session.commit()
    print(f"\nDone. {added} new bowlers, {updated} updated, {skipped} skipped.")
    print(f"Roster for {season.name} is ready.")

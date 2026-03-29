#!/usr/bin/env python3
"""
Seed the 2025-2026 historical season structure from the Week 22 scoring spreadsheet.

This creates the season record, teams, bowler records, roster entries, week
records, and schedule entries.  It does NOT import scores or team points —
use seed_week.py for that, one week at a time, so you can verify each week's
lane assignments against the actual results.

Run on Mac with Flask app stopped:
  python seed_historical.py "/path/to/scoring 2025-2026 - Week 22.xlsx"

After this completes, run:
  python seed_week.py 1  "/path/to/scoring 2025-2026 - Week 22.xlsx"
  python seed_week.py 2  "/path/to/scoring 2025-2026 - Week 22.xlsx"
  ... through week 21 (week 22 position night entered live through the app)
"""

import sys
import os
from datetime import date

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import create_app
from models import db, Season, Team, Bowler, Roster, Week, ScheduleEntry

# ─── 2025-2026 lane assignments ───────────────────────────────────────────────
# Format: (week_num, date, [team_on_17/19, team_on_18/20, team_on_21/23, team_on_22/24])
# Teams at positions [0,1] compete against each other on matchup_nums 1 & 2.
# Teams at positions [2,3] compete against each other on matchup_nums 3 & 4.
# Source: "Bowling Letter Schedule 25-26.docx" lane assignments table.
LANE_ASSIGNMENTS = [
    (1,  date(2025, 10,  6), [1, 2, 3, 4]),
    (2,  date(2025, 10, 13), [1, 3, 2, 4]),
    (3,  date(2025, 10, 20), [1, 4, 2, 3]),
    (4,  date(2025, 10, 27), [3, 4, 2, 1]),
    (5,  date(2025, 11,  3), [4, 2, 3, 1]),
    (6,  date(2025, 11, 10), [3, 2, 4, 1]),
    (7,  date(2025, 11, 17), [2, 1, 4, 3]),
    (8,  date(2025, 11, 24), [3, 1, 4, 2]),
    (9,  date(2025, 12,  1), [1, 4, 3, 2]),
    (10, date(2025, 12,  8), [2, 1, 3, 4]),
    # Week 11 = Position Night (Dec 15) — lane assignments set based on standings
    (12, date(2026,  1,  5), [2, 4, 1, 3]),
    (13, date(2026,  1, 12), [4, 1, 3, 2]),
    (14, date(2026,  1, 26), [1, 2, 4, 3]),
    (15, date(2026,  2,  2), [3, 1, 2, 4]),
    (16, date(2026,  2,  9), [2, 3, 1, 4]),
    (17, date(2026,  2, 23), [3, 4, 1, 2]),
    (18, date(2026,  3,  2), [1, 3, 4, 2]),
    (19, date(2026,  3,  9), [4, 1, 2, 3]),
    (20, date(2026,  3, 16), [1, 2, 3, 4]),
    (21, date(2026,  3, 23), [2, 4, 3, 1]),
    # Week 22 = Position Night (Mar 30) — lane assignments set based on standings
]

POSITION_NIGHTS = {
    11: date(2025, 12, 15),
    22: date(2026,  3, 30),
}

LANE_PAIRS = ["17/19", "18/20", "21/23", "22/24"]
SEASON_NAME = "2025-2026"
TOTAL_WEEKS = 22

NON_BOWLER_SHEETS = {
    'Instructions', 'Parameters', '2025 Banquet', 'wkly alpha', 'YTD alpha',
    'wkly high average', 'High Games ', 'team scoring', 'dummy', 'blinds',
    'Payout Formula', 'indiv payout', 'final handicap',
}


def load_wkly_alpha(wb):
    """Parse wkly alpha sheet. Returns dict: last_name -> {first, nickname, team_num, prior_handicap, active}"""
    ws = wb['wkly alpha']
    rows = list(ws.iter_rows(values_only=True))
    result = {}
    for row in rows[7:]:
        last = row[0]
        if last is None:
            continue
        last = str(last).strip()
        if last in ('6 games worksheet', 'weekly highs') or last == '':
            continue
        result[last] = {
            'first':          str(row[1]).strip() if row[1] else '',
            'nickname':       str(row[2]).strip() if row[2] else None,
            'team_num':       int(row[3]) if row[3] else None,
            'prior_handicap': int(row[14]) if row[14] else 0,
            'active':         str(row[15]).strip().lower() == 'yes' if row[15] else False,
        }
    return result


def load_team_names(wb):
    """Parse team names from team scoring header. Returns {team_number: name}."""
    ws = wb['team scoring']
    rows = list(ws.iter_rows(values_only=True))
    name_row = rows[5]
    teams = {}
    for val in name_row:
        if val and isinstance(val, str) and val.startswith('Team'):
            try:
                parts = val.split('(')
                num = int(parts[0].strip().split()[1])
                name = parts[1].rstrip(')')
                teams[num] = name.strip()
            except (IndexError, ValueError):
                pass
    return teams


def main():
    if len(sys.argv) < 2:
        print("Usage: python seed_historical.py <path_to_xlsx>")
        sys.exit(1)

    xlsx_path = sys.argv[1]
    if not os.path.exists(xlsx_path):
        print(f"File not found: {xlsx_path}")
        sys.exit(1)

    print(f"Loading workbook: {xlsx_path}")
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)

    alpha_data  = load_wkly_alpha(wb)
    team_names  = load_team_names(wb)
    print(f"Found {len(alpha_data)} bowlers, teams: {team_names}")

    app = create_app()
    with app.app_context():

        # ── Guard: skip if season already exists ──────────────────────────────
        existing = Season.query.filter_by(name=SEASON_NAME).first()
        if existing:
            print(f"\nSeason '{SEASON_NAME}' already exists (id={existing.id}).")
            resp = input("Delete and re-import structure? [y/N] ").strip().lower()
            if resp != 'y':
                print("Aborted.")
                return
            print("Deleting existing data…")
            sid = existing.id
            ScheduleEntry.query.filter_by(season_id=sid).delete()
            Roster.query.filter_by(season_id=sid).delete()
            Week.query.filter_by(season_id=sid).delete()
            Team.query.filter_by(season_id=sid).delete()
            db.session.delete(existing)
            db.session.commit()
            print("Deleted.")

        # ── 1. Season ─────────────────────────────────────────────────────────
        season = Season(
            name=SEASON_NAME,
            start_date=date(2025, 10, 6),
            num_weeks=TOTAL_WEEKS,
            half_boundary_week=11,
            handicap_base=200,
            handicap_factor=0.9,
            blind_scratch=125,
            blind_handicap=60,
            is_active=False,
        )
        db.session.add(season)
        db.session.flush()
        print(f"\nCreated season '{SEASON_NAME}' id={season.id}")

        # ── 2. Teams ──────────────────────────────────────────────────────────
        team_map = {}
        for num in sorted(team_names):
            t = Team(season_id=season.id, number=num, name=team_names[num])
            db.session.add(t)
            db.session.flush()
            team_map[num] = t
            print(f"  Team {num}: {team_names[num]}")

        # ── 3. Schedule ───────────────────────────────────────────────────────
        sched_count = 0
        for week_num, wk_date, lane_teams in LANE_ASSIGNMENTS:
            a1, a2, b1, b2 = lane_teams
            for mnum, t1, t2, lp in [
                (1, a1, a2, LANE_PAIRS[0]),
                (2, a1, a2, LANE_PAIRS[1]),
                (3, b1, b2, LANE_PAIRS[2]),
                (4, b1, b2, LANE_PAIRS[3]),
            ]:
                se = ScheduleEntry(
                    season_id=season.id, week_num=week_num, matchup_num=mnum,
                    team1_id=team_map[t1].id, team2_id=team_map[t2].id, lane_pair=lp,
                )
                db.session.add(se)
                sched_count += 1
        print(f"Created {sched_count} schedule entries (4 per regular week)")

        # ── 4. Weeks ──────────────────────────────────────────────────────────
        # Build date lookup from LANE_ASSIGNMENTS and POSITION_NIGHTS
        week_dates = {wk: d for wk, d, _ in LANE_ASSIGNMENTS}
        week_dates.update(POSITION_NIGHTS)

        for wk_num in range(1, TOTAL_WEEKS + 1):
            w = Week(
                season_id=season.id,
                week_num=wk_num,
                date=week_dates.get(wk_num),
                is_position_night=(wk_num in POSITION_NIGHTS),
                is_entered=False,
            )
            db.session.add(w)
        print(f"Created {TOTAL_WEEKS} week records")

        # ── 5. Bowlers & Roster ───────────────────────────────────────────────
        bowler_count = new_count = 0
        for last_name, info in alpha_data.items():
            team_num = info['team_num']
            if team_num not in team_map:
                print(f"  Skipped {last_name}: no team {team_num}")
                continue

            bowler = Bowler.query.filter_by(last_name=last_name).first()
            if not bowler:
                bowler = Bowler(
                    last_name=last_name,
                    first_name=info['first'],
                    nickname=info['nickname'],
                )
                db.session.add(bowler)
                db.session.flush()
                new_count += 1

            roster = Roster(
                bowler_id=bowler.id,
                season_id=season.id,
                team_id=team_map[team_num].id,
                active=info['active'],
                prior_handicap=info['prior_handicap'],
                joined_week=1,
            )
            db.session.add(roster)
            bowler_count += 1

        db.session.commit()
        print(f"Created/linked {bowler_count} roster entries ({new_count} new bowlers)")

        print(f"""
✓ Season '{SEASON_NAME}' structure imported.

Now import scores one week at a time:
  python seed_week.py 1  "{xlsx_path}"
  python seed_week.py 2  "{xlsx_path}"
  ...
  python seed_week.py 21 "{xlsx_path}"

Week 22 (position night) will be entered live through the app.
Each week will verify the lane assignment and create a JSON snapshot.
""")


if __name__ == '__main__':
    main()

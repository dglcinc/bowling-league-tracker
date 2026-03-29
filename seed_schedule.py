"""
Import lane assignments and week dates from the bowling letter schedule.

Usage (run on your Mac from the bowling-league-tracker directory):
    python seed_schedule.py

What it does:
- Populates ScheduleEntry for all regular weeks (weeks 1-21, skipping position nights)
- Updates Week dates for the active season (shifts 2025-2026 dates to 2026-2027)
- Position nights (weeks 11 and 22) are flagged but left without schedule entries
  since lane assignments depend on standings at that point

Lane pair structure (from the bowling letter schedule):
  Each week has 4 lane pairs: 17/19, 18/20, 21/23, 22/24
  Teams on pairs 17/19 and 18/20 compete against each other (matchups 1 & 2)
  Teams on pairs 21/23 and 22/24 compete against each other (matchups 3 & 4)
  This produces 4 score sheets per week, each worth 4 points = 16 points/week
"""

import sys
from datetime import date, timedelta
from app import create_app
from models import db, Season, Team, Week, ScheduleEntry

# Lane assignments parsed from "Pirate Bowling League Lane Assignments" table.
# Format: (week_num, [team_on_17/19, team_on_18/20, team_on_21/23, team_on_22/24])
# Dates are 2025-2026; they will be shifted +52 weeks for 2026-2027.
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
    # Week 11 = Position Night (Dec 15) — no fixed lane assignments
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
    # Week 22 = Position Night (Mar 30) — no fixed lane assignments
]

LANE_PAIRS = ["17/19", "18/20", "21/23", "22/24"]

# Position night week dates (for the DB even though no schedule entries)
POSITION_NIGHTS = {
    11: date(2025, 12, 15),
    22: date(2026,  3, 30),
}

app = create_app()

with app.app_context():
    season = Season.query.filter_by(is_active=True).first()
    if not season:
        print("ERROR: No active season. Create one in the app first.")
        sys.exit(1)

    print(f"Importing schedule into season: {season.name}")

    # Figure out year offset: shift 2025-2026 dates to match the new season's start year
    # The season name tells us the start year (e.g. "2026-2027" → start year 2026)
    try:
        start_year = int(season.name.split('-')[0])
    except (ValueError, IndexError):
        start_year = 2026  # default

    year_offset = start_year - 2025  # e.g. 2026-2025 = 1 year ahead
    day_shift = timedelta(days=364 * year_offset)  # shift by whole weeks (~1 year)

    teams = Team.query.filter_by(season_id=season.id).all()
    team_map = {t.number: t.id for t in teams}
    print(f"Teams: { {k: v for k,v in team_map.items()} }")

    # Clear existing schedule entries for this season
    deleted = ScheduleEntry.query.filter_by(season_id=season.id).delete()
    if deleted:
        print(f"  Cleared {deleted} existing schedule entries")

    entries_added = 0
    weeks_updated = 0

    for week_num, raw_date, lane_teams in LANE_ASSIGNMENTS:
        shifted_date = raw_date + day_shift

        # Update week date in DB
        wk = Week.query.filter_by(season_id=season.id, week_num=week_num).first()
        if wk:
            wk.date = shifted_date
            wk.is_position_night = False
            weeks_updated += 1

        # Lane structure:
        #   lane_teams[0] = team on 17/19   \  matchup A (matchup_num 1 and 2)
        #   lane_teams[1] = team on 18/20   /
        #   lane_teams[2] = team on 21/23   \  matchup B (matchup_num 3 and 4)
        #   lane_teams[3] = team on 22/24   /
        #
        # Each lane pair is a separate score sheet (matchup_num 1-4).
        # Both score sheets in a matchup pair the same two teams.

        team_a1 = lane_teams[0]   # team on 17/19
        team_a2 = lane_teams[1]   # team on 18/20 → plays against team_a1
        team_b1 = lane_teams[2]   # team on 21/23
        team_b2 = lane_teams[3]   # team on 22/24 → plays against team_b1

        matchup_defs = [
            (1, team_a1, team_a2, LANE_PAIRS[0]),  # Team A1 vs A2, lane pair 17/19
            (2, team_a1, team_a2, LANE_PAIRS[1]),  # Team A1 vs A2, lane pair 18/20
            (3, team_b1, team_b2, LANE_PAIRS[2]),  # Team B1 vs B2, lane pair 21/23
            (4, team_b1, team_b2, LANE_PAIRS[3]),  # Team B1 vs B2, lane pair 22/24
        ]

        for matchup_num, t1_num, t2_num, lane_pair in matchup_defs:
            entry = ScheduleEntry(
                season_id=season.id,
                week_num=week_num,
                matchup_num=matchup_num,
                team1_id=team_map[t1_num],
                team2_id=team_map[t2_num],
                lane_pair=lane_pair,
            )
            db.session.add(entry)
            entries_added += 1

        print(f"  Week {week_num:2d}  {shifted_date}  "
              f"T{team_a1} vs T{team_a2} (17-20)  |  "
              f"T{team_b1} vs T{team_b2} (21-24)")

    # Handle position nights — update dates, no schedule entries
    for week_num, raw_date in POSITION_NIGHTS.items():
        shifted_date = raw_date + day_shift
        wk = Week.query.filter_by(season_id=season.id, week_num=week_num).first()
        if wk:
            wk.date = shifted_date
            wk.is_position_night = True
            weeks_updated += 1
        print(f"  Week {week_num:2d}  {shifted_date}  POSITION NIGHT (schedule set at time of play)")

    db.session.commit()
    print(f"\nDone. {entries_added} schedule entries added, {weeks_updated} week dates updated.")
    print("Position nights (weeks 11 and 22) are flagged — enter lane assignments manually when standings are known.")

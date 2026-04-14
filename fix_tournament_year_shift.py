"""
One-time data migration: shift tournament placement entries one year earlier.

Background:
    For seasons 2004-2005 through 2016-2017, the Payout Formula sheet in each
    XLS contained the *prior* year's tournament winners (because each year's
    sheet was copied from the prior year and the Payout section wasn't updated).
    So the entries seeded into the DB are each one year too late.

What this script does:
    1. Creates a stub 2003-2004 season (no roster, no scores — just the four
       tournament Week rows) to receive the oldest displaced entries.
    2. For each of the 13 affected seasons (2004-2005 through 2016-2017):
         - Collects all tournament_entries WHERE place IS NOT NULL
         - Finds the prior season
         - Inserts each entry in the prior season's matching tournament week
         - Deletes the original entry
    3. After migration:
         - 2003-2004 has tournament placements (from the 2004-2005 XLS)
         - 2016-2017 has no placement entries (those winners are unknown)

Run with Flask app stopped:
    /opt/homebrew/bin/python3.11 fix_tournament_year_shift.py [--dry-run]
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DRY_RUN = '--dry-run' in sys.argv

from app import create_app
app = create_app()

# Seasons affected — in order; each entry will move to the prior
AFFECTED_SEASONS = [
    '2004-2005', '2005-2006', '2006-2007', '2007-2008', '2008-2009',
    '2009-2010', '2010-2011', '2011-2012', '2012-2013', '2013-2014',
    '2014-2015', '2015-2016', '2016-2017',
]

# Tournament types we shift (not club_championship — that's team-based, no place entries)
INDIVIDUAL_TT = ('indiv_scratch', 'indiv_hcp_1', 'indiv_hcp_2')


with app.app_context():
    from models import db, Season, Week, TournamentEntry
    from sqlalchemy import text
    from datetime import date, timedelta

    session = db.session

    print(f"{'DRY RUN — ' if DRY_RUN else ''}Tournament year shift")
    print("=" * 60)

    # ── 1. Create 2003-2004 stub season ───────────────────────────
    existing_2003 = Season.query.filter_by(name='2003-2004').first()
    if existing_2003:
        print(f"2003-2004 season already exists (id={existing_2003.id}) — skipping creation")
        season_2003 = existing_2003
    else:
        print("Creating 2003-2004 stub season…")
        from routes.admin import _POSTSEASON_WEEKS
        if not DRY_RUN:
            season_2003 = Season(
                name='2003-2004',
                start_date=date(2003, 9, 15),  # approximate
                num_weeks=22,
                half_boundary_week=11,
                is_active=False,
                bowling_format='single',
                venue='mountain_lakes_club',
                name_club_championship='Club Championship',
                name_indiv_scratch='Harry E. Russell Championship',
                name_indiv_hcp_1='Buzz Bedford Championship',
                name_indiv_hcp_2='Rose Bowl',
            )
            session.add(season_2003)
            session.flush()
            print(f"  Created season id={season_2003.id}")

            # Add only the four post-season tournament weeks (no regular weeks needed)
            last_date = date(2004, 4, 19)  # approximate last week
            for offset, (tt, is_pos) in enumerate(_POSTSEASON_WEEKS, start=1):
                wn = 22 + offset
                wk = Week(
                    season_id=season_2003.id,
                    week_num=wn,
                    tournament_type=tt,
                    is_position_night=is_pos,
                    is_entered=False,
                    date=last_date + timedelta(weeks=offset),
                )
                session.add(wk)
            session.flush()
            print(f"  Added tournament weeks 23–26 to 2003-2004")
        else:
            print("  [DRY RUN] would create 2003-2004 season with tournament weeks 23–26")
            season_2003 = None  # placeholder

    # ── 2. Build prior-season lookup ──────────────────────────────
    # Map season name → Season object
    all_seasons = {s.name: s for s in Season.query.all()}

    def prior_season_name(name):
        # '2005-2006' → '2004-2005'
        parts = name.split('-')
        y1, y2 = int(parts[0]), int(parts[1])
        return f'{y1-1}-{y2-1}'

    def get_tt_week(season_id, tt):
        """Return the week_num for the given tournament_type in a season."""
        wk = Week.query.filter_by(season_id=season_id, tournament_type=tt).first()
        return wk.week_num if wk else None

    # ── 3. Shift entries season by season ─────────────────────────
    total_moved = 0
    for season_name in AFFECTED_SEASONS:
        season = all_seasons.get(season_name)
        if not season:
            print(f"\nWARN: season {season_name} not found — skipping")
            continue

        prior_name = prior_season_name(season_name)
        prior = all_seasons.get(prior_name)
        if not prior and prior_name == '2003-2004':
            prior = season_2003  # just created
        if not prior:
            print(f"\nWARN: prior season {prior_name} not found — skipping {season_name}")
            continue

        # Get placement entries for this season
        entries = (TournamentEntry.query
                   .filter_by(season_id=season.id)
                   .filter(TournamentEntry.place.isnot(None))
                   .all())

        if not entries:
            print(f"\n{season_name}: no placement entries found")
            continue

        print(f"\n{season_name} → {prior_name} ({len(entries)} entries):")
        moved_count = 0
        for te in entries:
            # Find the tournament_type for this week in the source season
            src_week = Week.query.filter_by(
                season_id=season.id, week_num=te.week_num
            ).first()
            if not src_week or not src_week.tournament_type:
                print(f"  WARN: week {te.week_num} in {season_name} has no tournament_type — skipping")
                continue

            tt = src_week.tournament_type
            tgt_week_num = get_tt_week(prior.id, tt)
            if not tgt_week_num:
                print(f"  WARN: no {tt} week found in {prior_name} — skipping")
                continue

            bowler_name = f"{te.bowler.last_name if te.bowler else te.guest_name}, place={te.place}"
            print(f"  {tt} #{te.place}: {bowler_name}")

            if not DRY_RUN:
                new_te = TournamentEntry(
                    season_id=prior.id,
                    week_num=tgt_week_num,
                    bowler_id=te.bowler_id,
                    guest_name=te.guest_name,
                    handicap=te.handicap,
                    place=te.place,
                )
                session.add(new_te)
                session.delete(te)
                moved_count += 1
            else:
                moved_count += 1

        total_moved += moved_count
        print(f"  → {moved_count} entries {'queued' if DRY_RUN else 'moved'}")

    # ── 4. Summary ────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Total entries {'to move' if DRY_RUN else 'moved'}: {total_moved}")
    print("2016-2017 will have no placement entries after migration (winners unknown).")

    if DRY_RUN:
        print("\nDRY RUN complete — no changes written.")
        session.rollback()
    else:
        session.commit()
        print("\nAll changes committed.")

        # Verify
        print("\nVerification — placement entry counts by season:")
        result = session.execute(text('''
            SELECT s.name, COUNT(*) as cnt
            FROM tournament_entries te
            JOIN seasons s ON te.season_id = s.id
            WHERE te.place IS NOT NULL
              AND s.name BETWEEN '2003-2004' AND '2016-2017'
            GROUP BY s.name ORDER BY s.name
        ''')).fetchall()
        for row in result:
            print(f"  {row[0]}: {row[1]} entries")

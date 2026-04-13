"""
Repair historical tournament winner entries (seasons 2004-2017).

Deletes all TournamentEntry rows for seasons whose names start with "20"
(i.e., the historical imported seasons, not current ones), then re-seeds
them with verified winner data using proper first+last-name bowler lookup.

Run once: python3 repair_tournament_winners.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import db, Season, Bowler, TournamentEntry

# ---------------------------------------------------------------------------
# Verified winner data — derived directly from XLS Payout Formula sheets.
# Format: season_name -> {tournament_type -> [(place, "First Last"), ...]}
# tournament types: 'indiv_scratch' (Harry Russell / Club Championship)
#                   'indiv_hcp_1'   (Buzz Bedford)
#                   'indiv_hcp_2'   (Rose Bowl)
# ---------------------------------------------------------------------------
WINNERS = {
    "2004-2005": {
        "indiv_hcp_1":   [(1, "Bill Bethke"),   (2, "Mark Watrous"), (3, "Jim Zorlas")],
        "indiv_hcp_2":   [(1, "Steve Emr"),     (2, "Wayne Buckley"),(3, "Toby Frey")],
    },
    "2005-2006": {
        "indiv_hcp_1":   [(1, "Toby Frey"),     (2, "Joel Ramich"),  (3, "Steve Emr")],
        "indiv_hcp_2":   [(1, "Steve Fischer"), (2, "Dan Happer"),   (3, "Barry Stewart")],
    },
    "2006-2007": {
        "indiv_hcp_1":   [(1, "Toby Frey"),     (2, "Joel Ramich"),  (3, "Steve Emr")],
        "indiv_hcp_2":   [(1, "Steve Fischer"), (2, "Dan Happer"),   (3, "Barry Stewart")],
    },
    "2007-2008": {
        "indiv_hcp_1":   [(1, "Joel Ramich"),   (2, "Toby Frey"),    (3, "Tom Ross")],
        "indiv_hcp_2":   [(1, "Paul Zorlas"),   (2, "Jeff Rose"),    (3, "Mark Watrous")],
        "indiv_scratch": [(1, "Mark Watrous"),  (2, "Dave Shaw"),    (3, "Jeff Rose")],
    },
    "2008-2009": {
        "indiv_hcp_1":   [(1, "Joel Ramich"),   (2, "Toby Frey"),    (3, "Shep Belyea")],
        "indiv_hcp_2":   [(1, "Jack Sullivan"), (2, "Joel Ramich"),  (3, "Jim Brylawski")],
    },
    "2009-2010": {
        "indiv_hcp_1":   [(1, "Jack Renahan"),  (2, "Jack Sullivan"),(3, "Steve Emr")],
        "indiv_hcp_2":   [(1, "Chris Hatton"),  (2, "Jim Kinney"),   (3, "Dave Shaw")],
    },
    "2010-2011": {
        "indiv_hcp_1":   [(1, "Wayne Buckley"), (2, "Steve Emr"),    (3, "Jack Renahan")],
        "indiv_hcp_2":   [(1, "Bill Albergo"),  (2, "Dan Happer"),   (3, "Tom Ross")],
    },
    "2011-2012": {
        "indiv_hcp_1":   [(1, "Dan Happer"),    (2, "Joel Ramich"),  (3, "Jack Sullivan")],
        "indiv_hcp_2":   [(1, "Dan Happer"),    (2, "Bill Albergo"), (3, "Jack Renahan")],
    },
    "2012-2013": {
        "indiv_hcp_1":   [(1, "Peter Nix"),     (2, "Dennis Luc"),   (3, "Dan Happer")],
        "indiv_hcp_2":   [(1, "Giovanni Scolaro"), (2, "Jim Brylawski"), (3, "Peter Nix")],
    },
    "2013-2014": {
        "indiv_hcp_1":   [(1, "Peter Nix"),     (2, "Jim Bailey"),   (3, "Mark Gossett")],
        "indiv_hcp_2":   [(1, "Dan Happer"),    (2, "Jim Bailey"),   (3, "Terry Moran")],
        "indiv_scratch": [(1, "Steve Emr")],
    },
    "2014-2015": {
        "indiv_hcp_1":   [(1, "Al Paz"),        (2, "Jack Renahan"), (3, "Joel Ramich")],
        "indiv_hcp_2":   [(1, "Dave Shaw"),     (2, "Todd Terhune"), (3, "Peter Nix")],
    },
    "2015-2016": {
        "indiv_hcp_1":   [(1, "Dan Happer"),    (2, "Marc Walker"),  (3, "Jack Renahan")],
        "indiv_hcp_2":   [(1, "Jack Renahan"),  (2, "Jim Kinney"),   (3, "Shep Belyea")],
    },
    "2016-2017": {
        "indiv_hcp_1":   [(1, "Doug Kennedy"),  (2, "Steve Emr"),    (3, "Jack Sullivan")],
        "indiv_hcp_2":   [(1, "Jack Renahan"),  (2, "Chad Harris"),  (3, "Jim Brylawski")],
    },
}

# (offset table removed — we now look up week_num from Week rows at runtime)


def find_bowler(name):
    """Look up bowler by 'First Last' name using first+last matching."""
    parts = name.strip().split()
    if not parts:
        return None
    last = parts[-1]
    first = parts[0] if len(parts) > 1 else None

    candidates = Bowler.query.filter(Bowler.last_name.ilike(last)).all()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Multiple bowlers with same last name — match on first name initial
    if first:
        for c in candidates:
            if c.first_name and c.first_name.lower().startswith(first[0].lower()):
                return c
    return candidates[0]


def repair(dry_run=False):
    app = create_app()
    with app.app_context():
        # Only touch seasons covered by the WINNERS dict (2004-2017 historical imports).
        # Seasons 2017-2018 onward were manually entered and must not be disturbed.
        target_names = list(WINNERS.keys())
        historical_seasons = (Season.query
                              .filter(Season.name.in_(target_names))
                              .order_by(Season.name)
                              .all())
        season_map = {s.name: s for s in historical_seasons}

        # Count existing entries to be deleted
        historical_ids = [s.id for s in historical_seasons]
        existing = (TournamentEntry.query
                    .filter(TournamentEntry.season_id.in_(historical_ids))
                    .all())
        print(f"Found {len(existing)} existing tournament entries across {len(historical_seasons)} historical seasons.")

        if not dry_run:
            for te in existing:
                db.session.delete(te)
            db.session.flush()
            print("Deleted all existing historical tournament entries.")

        errors = []
        created = 0

        for season_name, tournaments in sorted(WINNERS.items()):
            season = season_map.get(season_name)
            if not season:
                print(f"  WARNING: season {season_name!r} not found in DB — skipping")
                continue

            # Look up week_num from existing Week rows by tournament_type
            from models import Week
            tt_to_wk_num = {
                w.tournament_type: w.week_num
                for w in Week.query.filter_by(season_id=season.id)
                               .filter(Week.tournament_type.isnot(None)).all()
            }

            print(f"\n{season_name} (id={season.id}) week map: {tt_to_wk_num}")

            for tt, placements in tournaments.items():
                wk_num = tt_to_wk_num.get(tt)
                if not wk_num:
                    errors.append(f"  {season_name}: no Week row for tournament_type={tt!r}")
                    print(f"  WARNING: no Week row for {tt}")
                    continue
                for place, name in placements:
                    bowler = find_bowler(name)
                    if not bowler:
                        errors.append(f"  {season_name} {tt} place={place}: {name!r} NOT FOUND")
                        status = "NOT FOUND"
                    else:
                        status = f"id={bowler.id}"

                    label = season.tournament_labels.get(tt, tt)
                    print(f"  {label} #{place}: {name} -> {status}")

                    if not dry_run and bowler:
                        te = TournamentEntry(
                            season_id=season.id,
                            week_num=wk_num,
                            bowler_id=bowler.id,
                            guest_name=None,
                            handicap=0,
                            place=place,
                        )
                        db.session.add(te)
                        created += 1

        if errors:
            print("\nERRORS:")
            for e in errors:
                print(e)

        if not dry_run:
            db.session.commit()
            print(f"\nCommitted {created} tournament entries.")
        else:
            print(f"\nDRY RUN — would create {created} entries (errors: {len(errors)})")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN ===")
    repair(dry_run=dry_run)

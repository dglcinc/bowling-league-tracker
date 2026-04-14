"""
One-time script: fix duplicate and mis-named bowler records.

Operations (in order):
  1. Brywlaski Jim (183) → Brylawski Jim (7)          [spelling fix]
  2. Kincey Damion (220) → Kincey Dameon (30)          [spelling fix]
  3. Oakley Glenn (255) → Oakley Glen (200)            [spelling fix]
  4. Graf Chuck (272) → Graf Charles (249)             [nickname variant; set nickname=Chuck]
  5. "Mike, Schmitt" (243) → Schmitt Mike (258)        [first/last swapped across seasons]
  6. "Mike, Tucker" (292) → Tucker Mike               [first/last swapped; rename in place]
  7. Martorana M (295) → first_name='Mike'            [initial only → full name]

Run with Flask app stopped:
    /opt/homebrew/bin/python3.11 fix_bowler_merges.py [--dry-run]
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DRY_RUN = '--dry-run' in sys.argv

from app import create_app
app = create_app()


def merge_bowlers(db, src_id, tgt_id, label, session):
    """Re-point all FK references from src → tgt, then delete src."""
    from sqlalchemy import text
    tables = [
        ('roster',             'bowler_id'),
        ('matchup_entries',    'bowler_id'),
        ('tournament_entries', 'bowler_id'),
        ('user_accounts',      'bowler_id'),
        ('push_subscriptions', 'bowler_id'),
    ]
    moved = {}
    for table, col in tables:
        # Check table exists
        exists = session.execute(text(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
        )).fetchone()
        if not exists:
            continue
        rows = session.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE {col} = :src"
        ), {'src': src_id}).scalar()
        if rows:
            if not DRY_RUN:
                session.execute(text(
                    f"UPDATE {table} SET {col} = :tgt WHERE {col} = :src"
                ), {'tgt': tgt_id, 'src': src_id})
            moved[table] = rows
    print(f"  {label}: moved {moved}")
    if not DRY_RUN:
        session.execute(text("DELETE FROM bowlers WHERE id = :id"), {'id': src_id})
        print(f"    deleted bowler id={src_id}")


with app.app_context():
    from models import db, Bowler
    from sqlalchemy import text

    print(f"{'DRY RUN — ' if DRY_RUN else ''}Bowler merge/fix script")
    print("=" * 60)

    session = db.session

    # ── 1. Brywlaski Jim → Brylawski Jim ──────────────────────────
    print("\n1. Brywlaski Jim (183) → Brylawski Jim (7)")
    merge_bowlers(db, src_id=183, tgt_id=7,
                  label="Brywlaski→Brylawski", session=session)

    # ── 2. Kincey Damion → Kincey Dameon ──────────────────────────
    print("\n2. Kincey Damion (220) → Kincey Dameon (30)")
    merge_bowlers(db, src_id=220, tgt_id=30,
                  label="Kincey Damion→Dameon", session=session)

    # ── 3. Oakley Glenn → Oakley Glen ─────────────────────────────
    print("\n3. Oakley Glenn (255) → Oakley Glen (200)")
    merge_bowlers(db, src_id=255, tgt_id=200,
                  label="Oakley Glenn→Glen", session=session)

    # ── 4. Graf Chuck → Graf Charles; set nickname ─────────────────
    print("\n4. Graf Chuck (272) → Graf Charles (249); nickname=Chuck")
    merge_bowlers(db, src_id=272, tgt_id=249,
                  label="Graf Chuck→Charles", session=session)
    if not DRY_RUN:
        session.execute(text(
            "UPDATE bowlers SET nickname = 'Chuck' WHERE id = 249"
        ))
        print("    set nickname=Chuck on id=249")

    # ── 5. "Mike, Schmitt" (243) → Schmitt Mike (258) ─────────────
    print("\n5. 'Mike, Schmitt' (243) → Schmitt Mike (258)")
    merge_bowlers(db, src_id=243, tgt_id=258,
                  label="Mike,Schmitt→Schmitt,Mike", session=session)

    # ── 6. "Mike, Tucker" (292) → rename to Tucker Mike ───────────
    print("\n6. 'Mike, Tucker' (292) → rename last='Tucker', first='Mike'")
    existing = session.execute(text(
        "SELECT id, last_name, first_name FROM bowlers WHERE id = 292"
    )).fetchone()
    print(f"    before: {existing}")
    if not DRY_RUN:
        session.execute(text(
            "UPDATE bowlers SET last_name='Tucker', first_name='Mike' WHERE id = 292"
        ))
        after = session.execute(text(
            "SELECT id, last_name, first_name FROM bowlers WHERE id = 292"
        )).fetchone()
        print(f"    after:  {after}")

    # ── 7. Martorana M → Mike ──────────────────────────────────────
    print("\n7. Martorana M (295) → first_name='Mike'")
    existing = session.execute(text(
        "SELECT id, last_name, first_name FROM bowlers WHERE id = 295"
    )).fetchone()
    print(f"    before: {existing}")
    if not DRY_RUN:
        session.execute(text(
            "UPDATE bowlers SET first_name='Mike' WHERE id = 295"
        ))
        after = session.execute(text(
            "SELECT id, last_name, first_name FROM bowlers WHERE id = 295"
        )).fetchone()
        print(f"    after:  {after}")

    if DRY_RUN:
        print("\nDRY RUN complete — no changes written.")
        session.rollback()
    else:
        session.commit()
        print("\nAll changes committed.")

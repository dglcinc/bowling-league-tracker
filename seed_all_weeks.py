#!/usr/bin/env python3
"""
Full historical import for the 2025-2026 season in one shot.

Run on Mac with Flask app stopped:
  python seed_all_weeks.py

This calls seed_historical.py (structure) then seed_week.py for weeks 1-21
in sequence.  Output from each step is printed as it runs so you can see
the lane-assignment verification for every week.
"""

import subprocess
import sys
import os

XLSX = "/users/david/OneDrive - DGLC/Claude/scoring 2025-2026 - Week 22.xlsx"
HERE = os.path.dirname(os.path.abspath(__file__))
PY   = sys.executable


def run(script, *args, auto_confirm=False):
    """Run a seed script, optionally auto-answering the 'delete?' prompt with 'y'."""
    cmd = [PY, os.path.join(HERE, script)] + list(args)
    inp = b"y\n" if auto_confirm else None
    result = subprocess.run(cmd, input=inp)
    return result.returncode


# ── 1. Structure: season, teams, bowlers, roster, weeks, schedule ─────────────
print("\n" + "="*60)
print("  STEP 1: Season structure")
print("="*60)

rc = run("seed_historical.py", XLSX, auto_confirm=True)
if rc != 0:
    print("\nERROR: seed_historical.py failed. Stopping.")
    sys.exit(1)

# ── 2. Scores: one week at a time, with lane-assignment verification ──────────
failed = []
for wk in range(1, 22):   # weeks 1–21; week 22 position night entered live
    rc = run("seed_week.py", str(wk), XLSX)
    if rc != 0:
        print(f"\n  ⚠  Week {wk} returned non-zero exit code ({rc}) — check output above.")
        failed.append(wk)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("  DONE")
print("="*60)
if failed:
    print(f"  Weeks with errors: {failed}")
    print("  Re-run those weeks individually to investigate:")
    for wk in failed:
        print(f'    python seed_week.py {wk} "{XLSX}"')
else:
    print("  All 21 weeks imported successfully.")
    print("  Week 22 (position night) will be entered live through the app.")
    print(f"  JSON snapshots saved to the snapshots/ folder in your OneDrive.")

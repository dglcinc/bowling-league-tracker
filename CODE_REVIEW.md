# Bowling League Tracker — Code Review

> Generated 2026-04-20. All file:line references verified against current source.

---

## Summary

The codebase is well-structured and functionally correct. The main issues are: (1) several identical or near-identical code blocks duplicated across routes that should be helpers, (2) an N+1 query pattern in the hot scoring path that issues 2+ DB queries per bowler per matchup, (3) two minor data-loss risks in the position-night save path, and (4) inconsistent cache invalidation between the two scoring entry points.

---

## 1. Duplicated Logic

### 1.1 Total-wood calculation — 5 copies

The expression `e.total_pins + (blind_hcp if e.is_blind else calculate_handicap(...)) * e.game_count` is written identically in:

| File | Lines | Context |
|------|-------|---------|
| `routes/entry.py` | 124–131 | `week_entry` recon block |
| `routes/entry.py` | 600–604 | `reconcile` route |
| `routes/reports.py` | 157–164 | `week_prizes` |
| `routes/reports.py` | 336–343 | `print_batch` |
| `routes/admin.py` | 1472–1478 | `_generate_prizes_pdf` |

**Fix:** Add a helper to `calculations.py`:

```python
def entry_handicap(entry, season, season_id, week_num):
    return season.blind_handicap if entry.is_blind else calculate_handicap(entry.bowler_id, season_id, week_num)

def entry_total_wood(entry, season, season_id, week_num):
    return entry.total_pins + entry_handicap(entry, season, season_id, week_num) * entry.game_count
```

All five call sites become one-liners.

### 1.2 "Leaders" list builder — 2 verbatim copies

The loop that builds the leaders list (bowler stats dict with average, games, handicap, HG/HS) is duplicated verbatim between `routes/reports.py:173–189` (week_prizes) and `routes/admin.py:1486–1499` (_generate_prizes_pdf). Both also duplicate the subsequent `avg_rows` filter-and-sort and the top-10 tie filter.

**Fix:** Extract to `calculations.py`:

```python
def build_leaders_list(season_id, through_week, min_games=None, top10=False):
    ...
```

### 1.3 Latest-entered-week query — 7+ copies

```python
Week.query.filter_by(season_id=..., is_entered=True).order_by(Week.week_num.desc()).first()
```

Appears in `app.py` (lines 349, 363, 446), `reports.py:315`, `admin.py:159`, `admin.py:269`, `mobile.py:164`. Variants add `is_cancelled=False`.

**Fix:** Model or calculations helper:
```python
def get_latest_entered_week(season_id, exclude_cancelled=False):
    q = Week.query.filter_by(season_id=season_id, is_entered=True)
    if exclude_cancelled:
        q = q.filter_by(is_cancelled=False)
    return q.order_by(Week.week_num.desc()).first()
```

### 1.4 Harry Russell top-10 tie filter — used in 3 places

The pattern `top10_avgs = set(sorted({...}[:10])); list = [x for x in list if x in top10_avgs]` appears at `calculations.py:829–830`, `reports.py:194–196`, and `reports.py:325–327` (and `admin.py:1503–1505`). Minor, but it's the same idiom each time and can be extracted.

---

## 2. Performance: N+1 Query in Scoring Path

**Severity: Medium — noticeable on every save, worse with more bowlers.**

`calculate_handicap()` (`calculations.py:38`) calls:
- `Roster.query.filter_by(...)` — 1 query
- `get_bowler_entries()` — 1 query (which itself queries `Week` to find tournament weeks, then queries `MatchupEntry`)

This is called once per non-blind bowler, per matchup, in `score_matchup` (`calculations.py:277`), `get_position_night_breakdown` (`calculations.py:414`), and `score_position_night` (`calculations.py:480`). For a 10-bowler matchup, that's ~30 DB queries to compute one matchup's points.

The same N+1 applies in the total-wood calculation in routes (entry.py:127, reports.py:160, etc.) — every time a page renders the recon block, it fires N handicap queries.

**Fix:** `calculate_handicap` already accepts a pre-fetched `entries` argument. The scoring functions should pre-fetch entries for all bowlers in the matchup once, then pass them through:

```python
# In score_matchup: pre-fetch all entries for all bowlers in this matchup
all_entries = MatchupEntry.query.filter_by(...).all()
bowler_ids = {e.bowler_id for e in all_entries if not e.is_blind}
entries_by_bowler = {bid: get_bowler_entries(bid, season_id) for bid in bowler_ids}
# Pass entries_by_bowler[entry.bowler_id] into calculate_handicap
```

---

## 3. Data-Loss Risk: Position Night Delete-Before-Insert

**Severity: Low probability, Medium impact.**

Two places delete all `TeamPoints` for a week then recalculate from scratch without an explicit transaction boundary:

- `entry.py:365–373` — inside `matchup_entry` POST for a position night
- `entry.py:525–532` — inside `position_entry` POST

If `score_position_night()` raises an exception after the delete and before the insert, the week's TeamPoints are gone (the outer request doesn't roll back automatically unless Flask-SQLAlchemy's rollback-on-exception is relied upon, which it is by default — but it's fragile).

**Fix:** Use a savepoint or restructure to insert new rows first, then delete old ones:
```python
# Calculate first, then atomically replace
pts = score_position_night(season_id, week_num)
TeamPoints.query.filter_by(season_id=season_id, week_num=week_num).delete()
for team_id, points in pts.items():
    db.session.add(TeamPoints(...))
```

This already matches entry.py:525–532's order, but the matchup_entry path at line 365 deletes before calling `score_position_night`. The fix there is to move the delete after the calculation (which is what position_entry already does). Also consider `db.session.begin_nested()` to ensure rollback goes to the savepoint rather than unwinding the whole request.

---

## 4. Cache Invalidation Inconsistency

`cache.clear()` is called after:
- `position_entry` POST when `week.is_entered` is set (`entry.py:546`)
- `tournament_placement` save (`admin.py:1753`)

But **not** after `matchup_entry` POST (`entry.py:398–409`) when `week.is_entered` is set for regular weeks. The Records page and Bowler Directory are cache-decorated and will serve stale data after the last matchup of a regular week is entered.

**Fix:** Add `cache.clear()` at `entry.py:408` after `week.is_entered = True`, parallel to what position_entry does.

---

## 5. Edge Case: Harry Russell Qualifier Count

`calculations.py:828–830`:
```python
top10_avgs = set(sorted({avg for avg, _ in qual_list}, reverse=True)[:10])
qual_list = [(avg, b) for avg, b in qual_list if avg in top10_avgs]
```

If more than 10 bowlers share the same average at the boundary (e.g., 11 bowlers average 176 and that's the 10th-unique average), all 11 are included. The qualifier display and "Who's Eligible" card show more than 10 names. This is technically correct per a "all ties qualify" interpretation, but may not match league intent if the list is supposed to be exactly 10.

**Recommended fix:** Document the intended behavior. If ties should all qualify, add a comment. If exactly 10 should qualify, break ties by bowler name.

---

## 6. Minor Issues

### 6.1 `is_blind` entry with null `bowler_id` only guarded in one path

`entry.py:603` correctly guards: `calculate_handicap(...) if e.bowler_id else 0`. But the inline version in `entry.py:127` (used for recon) does not guard — it calls `calculate_handicap(e.bowler_id, ...)` even if `e.bowler_id` is None. Since `calculate_handicap` starts with a `Roster.query.filter_by(bowler_id=None)` that returns nothing, it returns 0 safely — but only by accident. A null guard makes the intent explicit.

### 6.2 `_auto_assign_position_night` belongs in calculations.py

`entry.py:252–298` is pure business logic (reads standings, assigns schedule entries) with no routing concerns. It should move to `calculations.py` so it can be tested independently and reused without importing from a route module.

### 6.3 Repeated active-roster query pattern

```python
Roster.query.filter_by(season_id=season_id, active=True).join(Bowler).order_by(Bowler.last_name).all()
```

Appears in `entry.py:69`, `admin.py:164`, `admin.py:274`, `admin.py:1483`, `payout.py:130`, and `calculations.py:549`. Could be a helper, but low priority since it's a simple query.

### 6.4 `game_count or 3` default for blind entries

`calculations.py:275`, `412`, `478`:
```python
games = [season.blind_scratch] * (entry.game_count or 3)
```

If a blind entry has `game_count=0` (no games bowled), this silently defaults to 3 games, potentially inflating blind wood. `game_count` is a property on `MatchupEntry` that counts non-None game columns, so this shouldn't happen in normal operation — but the silent default hides the bug if it did. Consider asserting or logging instead.

### 6.5 `week.is_entered` set without `cache.clear()` in tournament_entry POST

`entry.py:705`: tournament entry saves set `week.is_entered = True` without clearing cache. Same inconsistency as §4 — low impact since tournament weeks don't affect Records stats, but worth aligning.

---

## Recommended Fix Order

| Priority | Issue | Effort |
|----------|-------|--------|
| 1 | Cache miss after regular-week entry (§4) | Tiny — one line |
| 2 | Position night delete-before-insert (§3) | Small — reorder 3 lines in matchup_entry |
| 3 | N+1 handicap queries in scoring path (§2) | Medium — refactor score_matchup and score_position_night |
| 4 | Extract `entry_handicap` / `entry_total_wood` helpers (§1.1) | Small — new helper + 5 call sites |
| 5 | Extract `build_leaders_list` helper (§1.2) | Medium — new helper + 2 call sites |
| 6 | Extract `get_latest_entered_week` helper (§1.3) | Small — new helper + 7 call sites |
| 7 | Move `_auto_assign_position_night` to calculations.py (§6.2) | Small — move + update import |
| 8 | Document / fix HR qualifier tie behavior (§5) | Tiny |
| 9 | Null guard on `e.bowler_id` in recon block (§6.1) | Tiny |

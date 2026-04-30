# Season Rollover Plan

Plan for an admin wizard that rolls one season forward into the next. No code yet — this document is a design proposal for review.

## 1. What a rollover means structurally

A "rollover" is the operation that takes a finished (or near-finished) Season N and produces a fresh Season N+1, ready for week-1 score entry.

**Records created:**
- One new `Season` row.
- Four `Team` rows for the new season (number 1–4) — current code at `routes/admin.py:48–108` already does this for new seasons.
- One `Roster` row per bowler carried over, with `prior_handicap` derived from Season N's final running average (Case 1 formula in CLAUDE.md: `ROUND((200 - running_avg) * 0.9)`). Bowlers with fewer than 6 games in Season N keep their existing `prior_handicap` value (Case 3).
- 22 regular `Week` rows + 4 post-season tournament `Week` rows (week_num 23–26 with `tournament_type` set per CLAUDE.md mapping). The existing `_add_postseason_weeks()` helper handles the latter.
- `ScheduleEntry` rows for regular weeks (skipping the two position nights), patterned after `seed_schedule.py`.
- `tournament_labels` defaulted from Season N's labels (already what `routes/admin.py:66–77` does for `new_season`).

**Records NOT created:** `MatchupEntry`, `TeamPoints`, `TournamentEntry`, `Snapshot`. These are produced as the season is bowled.

**The "prior_handicap from final running average" rule is the heart of rollover.** This is the one piece `seed_from_xls.py` does today by reading an XLS — the wizard replaces that read with a direct query against `get_bowler_stats(bowler_id, prior_season_id).running_avg`.

## 2. UX — admin wizard

A single multi-step form under `/admin/seasons/rollover` (one URL, step state in form fields, no DB writes until the final submit). Five steps, each with a back link:

### Step 1 — Source season
- Pick the source season (defaults to currently-active season).
- Show its end-of-season summary: total bowlers rostered, # active, # with ≥6 games, # without.
- Confirm: "use this as the basis for rollover."

### Step 2 — Identity & dates
- Name (default: increment year, e.g. `2025-2026 → 2026-2027`).
- `start_date` (week-1 date; cascades +7 days for the rest, same JS pattern as `edit_weeks.html`).
- `num_weeks` (default 22, locked in practice but editable).
- `half_boundary_week` (default 11).
- `bowling_format` (default: copy source).
- `venue` (default: copy source).
- `handicap_base`, `handicap_factor`, `blind_scratch`, `blind_handicap` (default: copy source; collapsible "advanced").

### Step 3 — Teams
- Four rows pre-filled from source season (`Team.name`, `Team.captain_name`).
- Editable per row. Order = team number (1–4).

### Step 4 — Roster
- Table of every bowler rostered in the source season, sorted alphabetically.
- Columns: name, source team, source running_avg, source cumulative_games, computed `prior_handicap`, **carry over?** (checkbox, default checked if `active=True` in source), **target team** (1–4 dropdown, default = source team).
- "Add bowler" link at bottom: free-text name search across all `Bowler` rows (covers returnees who weren't on the source roster).
- For carried-over bowlers with `<6` games in Season N: show the prior `prior_handicap` value being preserved, with a note ("kept from prior — fewer than 6 games"). For `≥6` games: show computed value.
- Mid-season retirees / dropouts: surface `joined_week` from source roster + active flag so the user can decide.

### Step 5 — Schedule & tournament labels
- Tournament display names — four inputs, defaulted from source season's `name_club_championship` / `name_indiv_scratch` / `name_indiv_hcp_1` / `name_indiv_hcp_2`.
- Schedule seeding — three options:
  - **Copy source season's lane assignments** (shift by exactly 26 weeks; matches `seed_schedule.py` +52-week pattern but generalised).
  - **Standard rotation** — generate a balanced round-robin so each team plays each opponent the same number of times across 22 weeks (pre-built table — same one `seed_schedule.py` uses today).
  - **Blank** — create no `ScheduleEntry` rows; admin will assign lanes weekly via the existing `assign_matchups` tool.
- Position nights (week 11 + week 22) — auto-assigned from standings later, no input needed.

### Final review & commit
- Diff-style summary: "Will create Season `2026-2027` with 4 teams, 26 weeks, 38 roster entries (37 carryover + 1 manually added), schedule seeded via standard rotation."
- "Deactivate source season" checkbox (default: checked).
- Submit creates everything inside one transaction. Redirect to the new season's home page.

## 3. Data integrity

- **Deactivate prior season** — single `is_active = False` write on the source season at the end of the transaction. Existing `new_season` route already does the equivalent via `Season.query.filter_by(is_active=True).update({'is_active': False})`.
- **Mid-season retirees** — surfaced in the roster step (Step 4). Default behaviour: if `Roster.active=False` in source, default the carryover checkbox to unchecked. Admin can override either way.
- **Joined-late bowlers** — `joined_week` resets to 1 on the new season's roster (everyone starts week 1). The source `joined_week` is shown only as informational context.
- **Blank vs seeded schedule** — explicit Step-5 choice. A blank schedule is supported today (assign-matchups tool fills in week by week), so this isn't risky; it just means the "Up Next" card doesn't show fixtures until each week is assigned.
- **Idempotency / re-run safety** — submitting twice must not create two `2026-2027` seasons. Enforce with a unique check on `Season.name` before commit; if it exists and is empty (no `MatchupEntry` rows), offer to wipe and redo; otherwise refuse.
- **Atomicity** — wrap the final write in a single SQLAlchemy transaction so a partial rollover can't be left behind. If anything raises, roll back; nothing is committed.

## 4. Edge cases

- **Missing prior handicaps** — bowler exists in prior season but has zero games (no `MatchupEntry` rows). Treat as Case 2 from CLAUDE.md: the wizard cannot compute a handicap; flag the row for the admin to enter manually, or default to 0 (handicap will recompute once the bowler bowls 6 games into the new season).
- **Format change (single ↔ double)** — only affects whether games 4–6 are exposed in the entry UI. No structural impact on rollover; the wizard exposes `bowling_format` in Step 2 and that's it.
- **Venue change** — same — single field on `Season`. No data migration needed; the venue badge in `bowler_detail.html` reads it per season.
- **Tournament-type rename mid-rollover** — handled by Step 5 inputs. Historical records for prior seasons keep their own labels because labels live on each `Season` row.
- **Previously-rostered bowler now wants to switch teams** — Step 4's "target team" dropdown handles this; default is source team but admin can change.
- **Bowler exists in DB but never rostered before** — Step 4's "Add bowler" search pulls from `Bowler` table (not just `Roster`), so any historical bowler can be added back in.
- **Brand-new bowler** — needs a `Bowler` row first. The wizard links out to the existing "add bowler" admin page rather than embedding bowler creation; this keeps the rollover flow focused.
- **Rollover during an unfinished season** — the wizard runs against any source season but warns if the source has fewer than `num_weeks` weeks marked `is_entered`. Allow override (an admin might rollover before the very last position night is entered, then come back and finish).

## 5. Phased implementation

**Phase 1 — MVP wizard (smallest shippable thing):**
- Steps 1–4 only. Schedule = blank (admin assigns weekly). Tournament labels = copied from source (no edit UI in the wizard; admin can use existing `edit_weeks` afterward).
- Re-uses `_add_postseason_weeks()` and the existing `new_season` Team-creation block.
- Roster carryover with the prior_handicap computation is the only genuinely new logic.
- Ships in one PR. Gives the admin a one-click rollover that's strictly faster than the current `seed_from_xls.py` + manual season creation flow.

**Phase 2 — Schedule seeding:**
- Add Step 5 schedule options (copy / standard rotation / blank). Lift the rotation table out of `seed_schedule.py` into a shared helper. Shipping order doesn't matter — Phase 1 already lets admins start the season; Phase 2 just removes the assign-matchups busywork.

**Phase 3 — Tournament label editor inside the wizard:**
- Inline the four tournament name inputs in Step 5. Cosmetic — `edit_weeks` already handles this post-creation.

**Phase 4 — Polish & safety nets:**
- Idempotency guard (refuse-or-wipe behaviour for re-runs).
- "Preview rollover" dry-run that shows the diff without committing.
- Roster-step bulk actions ("uncheck all inactive", "set everyone to source team").

The MVP is the right shipping target. The other phases are additive and can land independently as time permits.

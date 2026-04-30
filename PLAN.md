# Ralph Loop — Bowling League Tracker

Each task is one loop iteration. Work top-down. Branch from `main`, open a PR, do not merge — leave it for review. After opening the PR, check the box and commit the PLAN.md update on `main` (CLAUDE.md rule: only docs/context files push direct to main).

## Tasks

- [x] **Fix mobile scores tab for individual tournaments.** On the mobile app `/m` scores tab, selecting the Harry E. Russell (Harry Russell) or Chad Harris tournament weeks shows "no scores entered" even when `tournament_entries` rows exist for that week. Find the mobile scores route/template, trace why tournament weeks fall through to the empty state, and render the actual entries (bowler name or guest_name, per-game scores, handicap, total). Test by loading a 2025-2026 tournament week on mobile after entries exist. PR title: "Mobile scores: render individual tournament entries".

- [x] **Promote mobile view toggle to a top-level link.** The "Mobile view" / "Desktop view" switch currently lives inside the account menu dropdown. Move it to a visible top-level navbar link (both desktop and mobile navbars) so users don't have to open the account menu to switch. Keep the existing toggle endpoint/cookie behavior — only the link placement changes. PR title: "Promote mobile/desktop view toggle to top-level nav". (PR #119)

- [ ] **Draft season rollover plan in `SEASON_ROLLOVER_PLAN.md`.** This task is plan-only — no code changes. Write `SEASON_ROLLOVER_PLAN.md` covering: (1) what a rollover means structurally (new Season row, copying teams, deciding which roster entries carry over with prior_handicap derived from prior season's final running average, seeding 26 weeks, default tournament labels, schedule seed), (2) UX — admin wizard screens / steps and what the user picks vs. what's auto-computed, (3) data integrity — how to deactivate the prior season (`is_active=False`), what to do about mid-season retirees, blank schedule vs. seeded schedule, (4) edge cases — missing prior handicaps, format change (single↔double), venue change, (5) phased implementation — minimum-viable wizard first vs. full one-shot. Open a PR adding only this file for review. PR title: "Plan: season rollover wizard".

- [ ] **Fun Stats: add "Most Tournaments Won or Placed".** On the Records page Fun Stats tab, add two new leaderboards driven by `tournament_entries.place` (1, 2, or 3): (a) **per-tournament-type** — for each of the four tournament types (`club_championship`, `indiv_scratch`, `indiv_hcp_1`, `indiv_hcp_2`), top bowlers by count of placements (and separately, count of wins where place=1); (b) **overall** — top bowlers by total placements across all tournament types, with breakdown of 1st/2nd/3rd. Use bowler display names (handle nullable bowler_id — guest_name entries are write-ins; group those out or label as "guests"). Match the visual style of the other Fun Stats sections. PR title: "Fun Stats: most tournaments won or placed".

## Loop rules (read each iteration)

- Spawn subagents for codebase exploration, log/data digging, multi-file reads. Use `Explore` for read-only search and `general-purpose` for heavier research. Don't grep widely or read large files in the main context unless the target file/line is already known.
- Branch off `main` per task. Push and open a PR. Do not merge.
- After PR is open, edit this `PLAN.md` to check the box, commit on `main` with a one-line "why" message, push.
- If a task turns out to be ambiguous, make the judgment call, do the work, and explain the decision in the PR description. Do not block waiting for input.
- If no unchecked tasks remain, output `DONE` and stop.

# Bowling League Tracker — Project Context

## Overview

**Mountain Lakes Men's Bowling League** season tracker. The existing source of truth is an Excel workbook — analyzed but not committed (contains personal info). This project replaces it with a proper web application.

Season: 23 weeks (October – March). Currently in season 2025-2026, through week 22.
Teams: 4. Bowlers: ~65 total (mix of active and inactive).

**Important:** Never put player names, team names (which are player surnames), or any other personal information in the repository, code, comments, or documentation.

## Repo / Branch State (as of 2026-03-29)

- GitHub: `dglcinc/bowling-league-tracker` (private)
- Local clone: `~/github/bowling-league-tracker`
- `feature/initial-app`: all current feature work — PR #2 open against main
- `docs/readme`: README rewrite — PR #3 open against main
- Open PRs should be reviewed and merged before starting new feature work

## League Structure

### Weekly Format
- 4 matchups per week, each on one pair of lanes (1 score sheet per lane pair)
- Each team is split across 2 of the 4 matchups simultaneously
- Each matchup: 2 teams, up to 3 games (series), scored on a physical score sheet

### Score Sheet
- Two columns: one team per side
- Teams must have equal player count per lane — if short, add a **blind** (scratch=125, hcp=60 per game, configurable per season)
- 6 game slots per player per week: games 1–3 = primary session, games 4–6 = legacy second session (only top 3 used now)

### Points per Matchup (regular weeks)
- 1 point per game: team with higher total handicap pinfall wins (3 games = up to 3 pts)
- 1 point for series: team with higher total handicap wood wins
- Max 4 points per matchup; each team plays 2 matchups → max 8 points per team per week
- Forfeit: if a team has no players on a sheet, present team wins all 4 points

### Position Nights (weeks 11 and 22)
- Points aggregated across all 4 sheets for each team pairing (not per sheet)
- Per game: team with higher aggregate handicap total wins **2 points** (3 games = 6 possible)
- Series total: team with higher aggregate wood wins 2 more points
- Max 8 points per position-night matchup = 16 total weekly (same max as regular)
- Lane assignments determined by standings: top-2 teams play each other, bottom-2 play each other
- **Auto-assigned**: whenever prior week's scores are saved, the position night's ScheduleEntry rows update automatically if the position night hasn't been entered yet

## Key Formulas

### Handicap — Three Cases

**Case 1: Established bowler (≥ 6 cumulative games)**
```
handicap = ROUND((200 - prior_week_running_avg) * 0.9)
```

**Case 2: New bowler, no prior year handicap (< 6 games)**
```
handicap = ROUND((200 - tonight_avg) * 0.9)
```

**Case 3: Returning bowler with prior year handicap (< 6 games)**
```
handicap = prior_year_handicap  (unchanged until 6 games reached)
```

### "Use This Handicap" display rule
Show prior-year handicap if cumulative games ≤ 3, otherwise current calculated handicap. (6-game threshold governs actual calculation; 3-game threshold governs display on the print sheet.)

### Total Wood (recon)
```
total_wood = sum over all entries of: total_pins + (handicap × game_count)
```
Blind entries use season.blind_handicap (60) per game. Real bowlers use calculated handicap.

### High Series with Handicap
```
winning_set = whichever of games 1–3 or 4–6 had higher scratch total
high_series_hcp = high_series_scratch + (handicap × games_in_winning_set)
```

## Data Model

All stats computed on the fly from `matchup_entries` — nothing derived stored except JSON snapshots.

### Tables

- **bowlers**: id, last_name, first_name, nickname, email. Never deleted.
- **seasons**: id, name, start_date, num_weeks, half_boundary_week (default 11), handicap_base (200), handicap_factor (0.9), blind_scratch (125), blind_handicap (60), is_active
- **teams**: id, season_id, number (1–4), name
- **roster**: bowler_id, season_id, team_id, active, prior_handicap, joined_week
- **schedule**: season_id, week_num, matchup_num (1–4), team1_id, team2_id, lane_pair
- **weeks**: season_id, week_num, date, is_position_night, is_cancelled, is_entered, notes
- **matchup_entries**: season_id, week_num, matchup_num, team_id, bowler_id, is_blind, lane_side (A/B), game1–game6
- **team_points**: season_id, week_num, matchup_num, team_id, points_earned (Float — supports 0.5-pt ties)
- **snapshots**: season_id, week_num, snapshot_json, created_at

### Key notes
- `MatchupEntry.matchup_num` (1–4) identifies which lane pair — critical for correct scoring; historical data required manual assignment via admin Assign Matchups tool
- `TeamPoints.points_earned` is Float to handle tied games (0.5 pts each)

## Application Structure

### Stack
- Python 3 / Flask (port 5001), SQLAlchemy, SQLite
- Bootstrap 5, Jinja2 — no JS frameworks
- DB stored in OneDrive for auto-backup (see `config.py`); falls back to local `data/`
- `enumerate` registered as a Jinja2 global function — use `enumerate(x)`, NOT `x | enumerate`

### Routes / Blueprints

**`entry_bp`** (`/season/<id>/...`)
- `week_list` — pick a week to enter
- `week_entry` — week summary with matchup cards, recon totals, prize results
- `matchup_entry` — score entry form for one lane pair; saves points on POST; triggers position night auto-assignment
- `reconcile` — blind reconciliation view

**`reports_bp`** (`/reports/season/<id>/...`)
- `wkly_alpha` — alphabetical roster with YTD stats, printable landscape
- `ytd_alpha` — sorted by average descending, YTD column set
- `wkly_high_avg` — same columns as wkly_alpha, sorted by average with rank
- `standings` — summary tables + week-by-week scoring grid (A/B pts per team, cumulative)
- `high_games` — average leaders + top-10 HG/HS scratch & hcp; `?min_games=N` filter
- `bowler_detail` — full season week-by-week for one bowler
- `week_prizes` — per-week prize winners (4 categories with ties), team standings, YTD leaders
- `print_batch` — combined print page: Group 1 = 4× wkly alpha; Group 2 = alpha + YTD + high avg + high games

**`admin_bp`** (`/admin/...`)
- Season, team, roster, week, and schedule management
- `assign_matchups_list` / `assign_matchups` — per-week tool to assign bowlers to lane pair A or B

**`payout_bp`** (`/payout/season/<id>`)
- YTD prize counts per bowler, weekly prize history, Iron Man candidates, Most Improved

### Print batch groups
- **Group 1 (4 pages)**: 4 copies of Weekly Alpha — the physical hand-in score sheets
- **Group 2 (4 pages)**: Weekly Alpha + YTD Alpha + Weekly High Avg + High Games — report copies
- JS body-class technique isolates groups: `printGroup(n)` sets `print-group-N` on body, CSS hides the other group

### Snapshots
Written automatically after each week is fully entered. Stored as JSON at OneDrive path next to the DB.

## Current State (as of 2026-03-29)

### Seasons in DB
- **2026-2027** (active): roster seeded from `seed_from_xls.py`; `prior_handicap` loaded from current season final handicap; schedule seeded from `seed_schedule.py`
- **2025-2026** (inactive): structure + scores for weeks 1–21 imported via seed scripts; week 22 position night to be entered live through the app

### Seed scripts (run on Mac, Flask app stopped)
XLS path: `/users/david/OneDrive - DGLC/Claude/scoring 2025-2026 - Week 22.xlsx`

| Script | Purpose |
|--------|---------|
| `seed_from_xls.py <xlsx>` | Seeds 2026-2027 roster + prior handicaps from `wkly alpha` sheet |
| `seed_schedule.py` | Seeds lane-assignment schedule for the active season from DOCX |
| `seed_historical.py <xlsx>` | Seeds 2025-2026 structure: season, teams, bowlers, roster, weeks, schedule |
| `seed_week.py <week_num> <xlsx>` | Imports one week's scores + verifies lane assignment; saves JSON snapshot |
| `seed_all_weeks.py` | Runs `seed_historical.py` then `seed_week.py` for weeks 1–21 in sequence |

### Known technical notes
- SQLite writes must run natively on Mac (not from VM) — VirtioFS file locking doesn't support SQLite
- `TeamPoints.points_earned` is Float to support 0.5-pt ties from tied games
- Historical data uses `matchup_num = team_number` as a simplification; corrected per-week via Assign Matchups admin tool

### Still to build
- Season rollover wizard
- Merge open PRs (#2, #3) once verified

## Git Workflow

CLAUDE.md pushes directly to main. All other code and documentation changes use feature branches + PRs. See global CLAUDE.md for full workflow.

For `gh` CLI: token is embedded in the remote URL — prefix commands with:
```bash
GITHUB_TOKEN=$(git remote get-url origin | sed 's/.*:\(.*\)@.*/\1/')
```

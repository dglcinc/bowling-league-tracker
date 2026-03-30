# Bowling League Tracker — Project Context

## Overview

**Mountain Lakes Men's Bowling League** season tracker. The existing source of truth is an Excel workbook (`scoring 2025-2026 - Week 22.xlsx`) — analyzed but not committed (contains personal info). This project replaces it with a proper web application.

Season: 22 weeks (October – March). Currently in season 2025-2026, Week 22 (position night not yet bowled). Active season in DB is 2026-2027 (next season, roster seeded). Historical 2025-2026 season import in progress.
Teams: 4 (Team 1 Lewis, Team 2 Ferrante, Team 3 Belyea, Team 4 Mancini).
Bowlers: ~65 total (mix of active and inactive).

## League Structure

### Weekly Format
- 8 lanes per night, once a week
- 4 matchups per week, each on one pair of lanes (1 score sheet per lane pair)
- Each team is split across 2 of the 4 matchups simultaneously
- Each matchup: 2 teams competing, up to 3 games (series), scored on a physical score sheet

### Score Sheet
- Two columns: one team per side
- Teams must have equal player count per lane — if short, add a **blind** (scratch=125, hcp=60 per game, up to 3 games)
- Players can sub in/out; no one-time bowlers (everyone is a registered league member)
- Each bowler can bowl as often or as little as they like each season
- 6 game slots per player per week: top 3 = first night session, bottom 3 = second (legacy from twice-a-week era; now only top 3 used)

### Points per Matchup (regular weeks)
- 1 point per game: team with higher total **handicap** pinfall wins (3 games = 3 possible)
- 1 point for series: team with higher total handicap wood wins
- Max 4 points per matchup × 4 matchups = 16 total points distributed per week
- Each team participates in 2 matchups → max 8 points per team per week
- **Forfeit**: if a team has no players on a sheet, present team wins all 4 points and can bowl for stats

### Position Nights (weeks 11 and 22)
- Same player score/handicap entry as normal
- Points calculated by aggregating across **all 4 sheets** for each team pairing (not per sheet)
- Per game: team with higher aggregate handicap total wins **2 points** (3 games = 6 possible)
- Series total: team with higher aggregate wood wins **2 more points**
- Max 8 points per matchup × 2 matchups = 16 total (same weekly max)
- **Half winners**: team with most cumulative points after weeks 1–11 (first half) and weeks 12–22 (second half)

### Schedule
- Fixed at start of each season (which team pair plays on which lane pair each week)
- Rotation designed to ensure all teams play each other on different lanes over time
- Stored in DB; set up once per season during admin setup

## Key Formulas

### Average
```
average = ROUND(cumulative_season_pins / cumulative_season_games, 0)
```
- Rounded to nearest integer (not truncated)
- Cumulative across the full season

### Handicap — Three Cases

**Case 1: Established bowler (6+ cumulative games)**
```
handicap = ROUND((200 - prior_week_running_avg) * 0.9, 0)
```
- Uses previous week's cumulative running average (handicap for tonight was set by last week's results)
- Applies whether or not they bowled this week

**Case 2: New bowler, no prior year handicap (first 6 games)**
```
handicap = ROUND((200 - tonight_avg) * 0.9, 0)
  where tonight_avg = tonight_total_pins / tonight_games_bowled
```
- Recalculated fresh each night from that session's games only (not cumulative)
- Applies until cumulative games crosses 6

**Case 3: Returning bowler with prior year handicap (first 6 games)**
```
handicap = prior_year_handicap
```
- Prior year handicap used unchanged until 6 cumulative games bowled
- Then switches to Case 1 formula

### High Game Scratch
```
high_game_scratch = MAX(game1, game2, game3, game4, game5, game6)
```

### High Game with Handicap
```
high_game_hcp = high_game_scratch + handicap  (0 if didn't bowl)
```

### High Series Scratch
```
high_series_scratch = MAX(SUM(games 1–3), SUM(games 4–6))
```
Takes the better of the two 3-game sets (handles double-night legacy).

### High Series with Handicap
```
winning_set = whichever of games 1–3 or 4–6 had higher scratch total
high_series_hcp = high_series_scratch + (handicap × COUNT(games in winning_set))
```

### Cumulative 2nd Half
Starts accumulating at week 12 (second half of 23-week season).

### "Use This Handicap" (wkly alpha display)
The printable roster shows prior-year handicap if cumulative games ≤ 3, otherwise current calculated handicap. This is intentional for the print sheet (switches after first night is entered). The 6-game threshold governs the actual handicap calculation; the display just needs to show what's relevant for the current night.

## Data Model

### Multi-year design
All data is scoped to a `season`. Bowlers exist outside seasons; per-season `roster` records track active status, team, and starting handicap.

### Tables
- **bowlers**: id, last_name, first_name, nickname, email, created_at. Never deleted — mark inactive instead.
- **seasons**: id, name (e.g. "2025-2026"), start_date, num_weeks, half_boundary_week (default 11)
- **roster**: bowler_id, season_id, team_id, active, prior_handicap, joined_week (for mid-season additions)
- **teams**: id, season_id, name, captain
- **schedule**: season_id, week_num, matchup_num (1–4), team1_id, team2_id, lane_pair
- **weeks**: season_id, week_num, date, is_position_night, notes
- **matchup_entries**: season_id, week_num, matchup_num, team_id, bowler_id, lane_side (A/B), is_blind, game1..game6 (nullable)
- **team_points**: season_id, week_num, matchup_num, team_id, points_earned
- **season_snapshots**: season_id, week_num, snapshot_json, created_at

All stats (average, handicap, cumulative totals, high game/series, team standings) are computed from `matchup_entries` on the fly — nothing derived is stored except snapshots.

## Application Design

### Stack
- **Python 3 + Flask** — web framework, runs locally with `python app.py`
- **SQLite** via SQLAlchemy — single `.db` file
- **Bootstrap 5** — layout and print-friendly CSS
- **No JavaScript frameworks** — plain HTML forms

### Storage location
- DB file: `~/OneDrive - DGLC/Claude/bowling-league-tracker/league.db` (OneDrive-backed, auto-synced)
- JSON snapshots: `~/OneDrive - DGLC/Claude/bowling-league-tracker/snapshots/YYYY-YYYY-wkNN.json`
- Snapshot written automatically after each weekly entry is saved

### Pages / Features

1. **Weekly entry**: pick week → 4 matchup sheets → assign players/blinds per lane → enter game scores. Points calculated automatically on save.
2. **Wkly Alpha (printable)**: roster with current avg, handicap, YTD stats. Prints from browser. Shows prior-week highs.
3. **Standings**: team points table (current half + overall), individual average leaders, high game/series records.
4. **Bowler detail**: full season history for one bowler.
5. **Blinds reconciliation**: enter headcount/blind count, compare against entered data.
6. **Payout tracker**: running prize calculations — high game/series scratch & hcp by week, most improved, iron man candidates, prize pool.
7. **Admin / Season setup**: roster management (add/activate/deactivate bowlers), season parameters (weeks, dates, schedule), prior-year handicap entry.
8. **XLS import**: reads end-of-season spreadsheet to seed next season (roster from `wkly alpha`, final handicaps from `final handicap` sheet). Optionally imports full score history from individual player tabs.
9. **Season rollover**: wizard to start new season — confirm active players, set teams, carry forward handicaps.

### Build Order
1. DB schema and SQLAlchemy models
2. Season setup + roster admin
3. Weekly score entry (core loop)
4. Wkly Alpha printable page
5. Standings and bowler detail
6. Blinds reconciliation
7. Payout tracker
8. XLS import tool
9. Season rollover wizard

## Current State (as of March 2026)

### What's been built
- Full Flask + SQLAlchemy + SQLite app, running on port 5001 (avoids macOS AirPlay conflict on 5000)
- All models, routes (admin, entry, reports, payout), templates, calculations, snapshots
- Bootstrap 5 CDN, print-friendly CSS for Wkly Alpha
- `feature/initial-app` branch open as PR — not yet merged

### Seasons in DB
- **2026-2027** (active): roster seeded from `seed_from_xls.py` using `wkly alpha` sheet; `prior_handicap` loaded from current season final handicap; schedule seeded from `seed_schedule.py` using the DOCX schedule letter
- **2025-2026** (inactive, in progress): structure seeded via `seed_historical.py`; per-week scores imported via `seed_week.py` weeks 1–21; week 22 position night entered live through the app after bowling

### Seed scripts (run on Mac, Flask app stopped)
All scripts live in `~/github/bowling-league-tracker/`. XLS path: `/users/david/OneDrive - DGLC/Claude/scoring 2025-2026 - Week 22.xlsx`

| Script | Purpose |
|--------|---------|
| `seed_from_xls.py <xlsx>` | Seeds 2026-2027 roster + prior handicaps from `wkly alpha` sheet |
| `seed_schedule.py` | Seeds lane-assignment schedule for the active season from DOCX |
| `seed_historical.py <xlsx>` | Seeds 2025-2026 structure: season, teams, bowlers, roster, weeks, schedule |
| `seed_week.py <week_num> <xlsx>` | Imports one week's scores + verifies lane assignment; saves JSON snapshot |
| `seed_all_weeks.py` | Runs `seed_historical.py` then `seed_week.py` for weeks 1–21 in sequence |

### Lane assignment verification (seed_week.py)
Two teams that compete share exactly 8 points between them each week. `seed_week.py` checks which team-total pairs sum to 8 and compares to the printed schedule. If a week's actual assignment differed from the schedule, it's detected automatically and the ScheduleEntry is updated.

### Known technical notes
- SQLite writes must run natively on Mac (not from VM) — VirtioFS file locking doesn't support SQLite
- `TeamPoints.points_earned` is Float (not Integer) to handle 0.5-pt ties from tied games
- MatchupEntry uses `matchup_num = team_number` as a simplification for historical data; individual stats don't use matchup_num so this is safe
- TeamPoints for historical seasons come from the spreadsheet directly, not recomputed from scores

### Still to build
- Season rollover wizard
- Position night week 22 entry (live, through the app UI)
- Merge `feature/initial-app` PR once historical import is verified

## Git Workflow

Feature branches + PRs for all code changes. See global CLAUDE.md (`~/github/claude-contexts/CLAUDE.md`).

## Repo
- GitHub: `dglcinc/bowling-league-tracker` (private)
- Local clone: `~/github/bowling-league-tracker`
- VM mount: `/sessions/<session>/mnt/github/bowling-league-tracker`

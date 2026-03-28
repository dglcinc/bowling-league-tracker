# Bowling League Tracker — Project Context

## Overview

**Mountain Lakes Men's Bowling League** season tracker. The existing source of truth is an Excel workbook (`scoring 2025-2026 - Week 20.xlsx`) with one sheet per bowler plus summary sheets. This project aims to replace or augment that workbook with a proper application.

Season: 23 weeks (October – March), currently in Week 20 (2025-2026).
Teams: 4 (Team 1 Lewis, Team 2 Ferrante, Team 3 Belyea, Team 4 Mancini).
Bowlers: ~65 total (mix of active and inactive).
Games per week: 3 standard; weeks with double-night have 6 (rows 9–14 in individual sheets).

## Source Spreadsheet Structure

### Parameters Sheet
- Season start date: October 6, 2025
- Date offsets for all 23 weeks (used by bowler sheets via lookup)
- Procedures documentation

### Individual Bowler Sheets (one per bowler, e.g. `LewisD`)

Row layout (columns A–Y = weeks 1–23 in cols C–Y):
- Row 1: Bowler name
- Row 2: Team
- Row 3: Active status
- Row 4: Handicap base (200)
- Row 5: Handicap factor (0.9)
- Row 6: Prior handicap (from prior year)
- Row 7: Week numbers 1–23 (cols C–Y)
- Row 8: Week dates (pulled from Parameters sheet)
- Rows 9–14: Game 1 – Game 6 scores (games 4–6 used for double-night weeks only)
- Row 15: Weekly total (`=SUM` of game rows for that week)
- Row 16: Cumulative total (running sum of row 15)
- Row 17: Running average (cumulative total / cumulative games played)
- Row 18: Handicap for that week (`=INT(factor * (base - average))`, i.e. `INT(0.9 * (200 - avg))`)
- Row 19: Cumulative game count
- Row 20: Weekly high game scratch
- Row 21: Weekly high game with handicap
- Row 22: Weekly high series scratch
- Row 23: Weekly high series with handicap
- Row 24: Red pins (weekly)
- Rows 27–30: YTD running highs (high game scratch, high game w/hcp, high series scratch, high series w/hcp)
- Row 31: Cumulative 2nd-half total (weeks 12+)

### `wkly alpha` Sheet — Master Roster
Columns (approximate): Name, First, Nickname, Team, Total (pins), 2nd-half total, Games played, Average, Handicap (canonical — use this column), Current Hcp, High Game Scratch, High Game w/Hcp, High Series Scratch, High Series w/Hcp, Last Year's Hcp, Active flag, Prize Paid flag, Banquet flag.

~55 active + inactive bowlers listed. This is the authoritative roster.

### `YTD alpha` Sheet
Similar to wkly alpha; sorted differently, YTD focus.

### `team scoring` Sheet
4 teams. Weekly A+B points per team; running point totals. Maximum 16 points per week distributed across all teams.

### `blinds` Sheet
Per-week blind game count, total wood (total pins for absent bowlers), player count.

### `indiv payout` Sheet
Per-bowler prize tracking columns: Iron Man, Most Improved, Biggest Fail, Belyea Championship, Chad Harris, Club Championship, High Average, High Game/Series for year, Weekly High Games (count of weeks each bowler won). Prize dollar amounts per category.

### `Payout Formula` Sheet
- $100/bowler entry, 40 paying bowlers → ~$3,170 total prize pool
- Prize breakdown:
  - High Average: 1st $125 / 2nd $100 / 3rd $75
  - High Series scratch/hcp: $75 each
  - High Game scratch/hcp: $75 each
  - Most Improved: $50
  - Iron Man: $50
  - Red Pins: $3 each occurrence
  - Tournaments: Belyea Championship, Chad Harris Memorial

### `final handicap` Sheet
Prior-year handicap lookup table for all bowlers (used to seed starting handicap).

### `High Games` / `wkly high average` Sheets
Weekly high game and average leaders tracking.

## Key Formulas

### Handicap
```
handicap = INT(0.9 * (200 - current_average))
```
- Base: 200
- Factor: 0.9
- Applied to running average after each week
- Prior year handicap used as starting value

### Running Average
```
average = cumulative_pins / cumulative_games
```
Cumulative games = sum of games actually bowled (not blind/absent weeks).

### Handicap Score
```
handicap_game = scratch_game + handicap
handicap_series = scratch_series + (handicap * games_in_series)
```

### Team Points
Each week: teams compete; A points + B points distributed based on results (max 16 total per week across all teams — 4 per head-to-head pairing).

### Iron Man
Bowler must bowl every week of the season. Tracked on `indiv payout` sheet.

## Application Goals

1. **Score entry**: Enter game scores by week for each bowler
2. **Automatic handicap calculation**: Recalculate after each week's entry
3. **Standings**: Team standings (points), individual average leaders
4. **Payout tracking**: High game/series winners, Iron Man candidates, Most Improved
5. **Reports**: Weekly summary, YTD standings, prize payout preview

## Tech Stack (to be decided)

No stack chosen yet. Options:
- Python + SQLite (simple, deployable on Pi or Mac)
- Python + FastAPI + React (web UI)
- Keep in Excel but add Python scripts for automation

## Files

- `scoring 2025-2026 - Week 20.xlsx` — source spreadsheet (reference only, not committed)
- `CLAUDE.md` — this file

## Repo
- GitHub: `dglcinc/bowling-league-tracker` (private)
- Clone: `~/github/bowling-league-tracker`

## Working Style
See global CLAUDE.md (`~/github/claude-contexts/CLAUDE.md`) for git workflow, PR conventions, and working style preferences.

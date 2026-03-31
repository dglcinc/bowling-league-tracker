# Bowling League Tracker

A Flask web application for managing a recreational ten-pin bowling league. Replaces a hand-maintained Excel workbook with a proper application for score entry, handicap calculation, standings, prize tracking, and printable weekly reports.

## Features

### Score Entry
- Per-week matchup cards for each lane pair — each team's bowlers entered on one screen
- Responsive layout scales from laptop to wide monitor
- Blind entries (absent bowlers) selected from the bowler dropdown; configurable scratch score and handicap per game
- Single-night format (3 games) or double-night format (6 games) — configurable per season
- Scores saved immediately per matchup; week marked entered when all matchups are complete
- Week-level summary with inline score tables, recon totals, and prize results
- Cancelled week support (e.g. snow cancellation) — toggled from the week list or week entry page

### Handicap Calculation
Handicap is computed fresh from raw scores each time — nothing derived is stored in the database.

```
handicap = ROUND((base − prior_average) × factor)   # e.g. base=200, factor=0.9
```

Rules applied in order:
1. **Established bowler** (≥ 6 games in the current season): use running average through the prior week
2. **Returning bowler** (< 6 games, has a prior-season handicap): use prior-season handicap unchanged
3. **New bowler** (< 6 games, no prior record): calculate from tonight's average

### Scoring and Points
- Regular weeks: 1 point per game (best handicap total wins), 1 point for series — up to 4 points per matchup
- Position nights: points aggregated across both lane pairs for each team pairing — top-2 teams by standings play each other, bottom-2 play each other
- Position night lane assignments update automatically whenever the prior week's scores are saved
- Forfeits handled: present team receives all 4 points if opponent has no bowlers

### Post-Season Tournaments
Four tournament weeks are automatically appended to each season after the regular schedule. Tournament scores are not counted toward season averages or handicaps.

| Tournament | Format | Notes |
|-----------|--------|-------|
| Club Team Championship | Team competition, position-night scoring | Uses standard matchup entry |
| Harry E. Russell Championship | Individual, 5-game scratch | All bowlers (active + inactive) + write-in option for non-league participants |
| Chad Harris Memorial Bowl | Individual, 3-game handicap | Active bowlers only |
| Shep Belyea Open | Individual, 3-game handicap | Active bowlers only |

The individual tournament entry form shows live rankings that update as scores are typed.

### Reports

| Report | URL | Description |
|--------|-----|-------------|
| Weekly Alpha | `/reports/season/<id>/alpha/<week>` | All bowlers alphabetical with YTD stats and handicap; week selector; printable landscape |
| YTD Alpha | `/reports/season/<id>/ytd-alpha/<week>` | Same data sorted by average descending with rank; fewer columns |
| Weekly High Avg | `/reports/season/<id>/high-avg/<week>` | Same columns as Weekly Alpha, sorted by average with rank |
| Team Standings | `/reports/season/<id>/standings` | Summary tables (overall, first half, second half) plus week-by-week scoring grid |
| High Games & Averages | `/reports/season/<id>/high-games` | Average leaders and top-10 lists for HG/HS scratch and handicap; filterable by minimum games |
| Per-Week Prizes | `/reports/season/<id>/week/<week>/prizes` | Four prize categories with tie handling; team standings; YTD leaders |
| Bowler Detail | `/reports/season/<id>/bowler/<id>` | Individual bowler week-by-week breakdown |
| Payout Overview | `/payout/season/<id>` | YTD prize counts, weekly prize history, Iron Man candidates, Most Improved |

### Print Batch
A single page (`/reports/season/<id>/print-batch/<week>`) assembles all weekly print materials:

- **Print Group 1** — 4 copies of Weekly Alpha (hand-in score sheets)
- **Print Group 2** — Weekly Alpha + YTD Alpha + Weekly High Avg + High Games (report copies)
- **Print All** — all 8 pages in one job

### Administration
- Season creation with configurable weeks, half-boundary, handicap formula, bowling format, and blind score defaults
- Team names set at season creation; roster management with carried-over handicap from prior season
- Week management: set dates (enter first date, subsequent weeks auto-fill at +7 days), mark position nights and tournament types, mark cancellations
- Schedule setup: lane pair assignments per week
- XLS import: upload an end-of-season spreadsheet to seed a full historical season (roster, scores, standings)
- Assign Matchups tool: for each week, assign bowlers to lane pair A or B — useful for correcting historical data
- Per-bowler Stats link in the roster table for quick access to the bowler detail report

## Data Model

```
Season  ──< Team ──< Roster ──> Bowler
        ──< Week
        ──< ScheduleEntry     (which teams bowl which matchup each week)
        ──< MatchupEntry      (one bowler's scores for one matchup)
        ──< TeamPoints        (points earned per team per matchup)
        ──< TournamentEntry   (individual tournament scores, not in season stats)
        ──< Snapshot          (weekly JSON snapshot for backup)
```

All statistics (averages, handicaps, high games, standings) are computed on the fly from `MatchupEntry` rows. Nothing derived is stored.

### Key model fields

**Season** — `bowling_format`: `'single'` (G1–G3, 8 lanes) or `'double'` (G1–G6, 4 lanes).

**Week** — `tournament_type`: null for regular weeks; `'club_championship'`, `'harry_russell'`, `'chad_harris'`, or `'shep_belyea'` for post-season weeks.

**MatchupEntry** — one bowler's session for one matchup:
- `game1`–`game3`: primary night scores
- `game4`–`game6`: second-night scores (double-night format)
- `is_blind`: absent bowler placeholder; uses season's `blind_scratch` and `blind_handicap`
- `matchup_num` (1–4): which lane pair this bowler was on

**TournamentEntry** — individual tournament score; `bowler_id` is nullable (write-in participants use `guest_name` instead).

**TeamPoints** — `points_earned` is Float to support 0.5-point ties.

## Tech Stack

- **Python 3** / **Flask** — web framework and routing (port 5001)
- **SQLAlchemy** — ORM; SQLite database stored in OneDrive folder for automatic cloud backup
- **Jinja2** — templating
- **Bootstrap 5** — responsive layout and print utilities
- No JavaScript frameworks — vanilla JS for blind auto-fill, date cascade, live tournament rankings, and print group isolation

## Project Layout

```
bowling-league-tracker/
├── app.py                  # App factory, blueprint registration, DB migration
├── config.py               # DB path (OneDrive-backed), snapshot dir
├── models.py               # SQLAlchemy models
├── calculations.py         # All stat computation (pure functions, no DB writes)
├── snapshots.py            # Weekly JSON snapshot writer
├── routes/
│   ├── admin.py            # Season, team, roster, week, schedule, XLS import
│   ├── entry.py            # Score entry, matchup forms, tournament entry, points calculation
│   ├── reports.py          # All report views
│   └── payout.py           # Prize payout overview
├── templates/
│   ├── base.html
│   ├── admin/              # Season/roster/schedule admin pages
│   ├── entry/              # Score entry and tournament entry pages
│   ├── reports/            # Report and print pages
│   └── payout/
└── seed_*.py               # One-time data import scripts (historical XLS import)
```

## Setup

### Requirements

```
flask
flask-sqlalchemy
openpyxl          # only needed for XLS import (seed scripts and web import)
```

Install:
```bash
pip install flask flask-sqlalchemy openpyxl
```

### Running

```bash
python app.py
```

The app runs on port 5001. The SQLite database is created automatically on first run, placed in the OneDrive-backed folder if available, otherwise in a local `data/` directory. Database migrations (new columns, backfills) run automatically on startup.

### First-time setup

1. Go to `/admin/seasons` and create a season — set the number of weeks, bowling format, and team names
2. Add bowlers to the roster under Admin → Season
3. Set up the weekly schedule (lane assignments) under Admin → Schedule
4. Set week dates under Admin → Week Dates — enter the first date and subsequent weeks auto-fill at weekly intervals

Four post-season tournament weeks are created automatically; their order can be adjusted by changing the tournament type dropdown in Week Dates.

### Importing a historical season

Use `/admin/import_season` to upload an existing Excel workbook. The import reads `wkly alpha` for roster, individual bowler sheets for game scores, and `team scoring` for team standings.

## Configuring for a Different League

All configuration (team count, number of weeks, handicap formula, blind scores, bowling format) is per-season in the admin UI. The handicap formula defaults (base 200, factor 0.9) can be adjusted for different league rules.

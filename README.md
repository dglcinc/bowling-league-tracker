# Bowling League Tracker

A Flask web application for managing a recreational ten-pin bowling league. Replaces a hand-maintained Excel workbook with a proper application for score entry, handicap calculation, standings, prize tracking, and printable weekly reports.

## Features

### Score Entry
- Per-week matchup cards for each lane pair — each team's bowlers entered on one screen
- Responsive layout scales from laptop to wide monitor
- Blind entries (absent bowlers) with configurable scratch score and handicap per game
- Scores saved immediately per matchup; week marked entered when all matchups are complete
- Week-level summary with inline score tables, recon totals, and prize results
- Cancelled week support (e.g. snow cancellation) — marked separately, no points awarded

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
- Position nights (weeks determined by `is_position_night` flag): points aggregated across both lane pairs for each team pairing — top-2 teams by standings play each other, bottom-2 play each other
- Position night lane assignments update automatically whenever the prior week's scores are saved
- Forfeits handled: present team receives all 4 points if opponent has no bowlers

### Reports

| Report | URL | Description |
|--------|-----|-------------|
| Weekly Alpha | `/reports/season/<id>/alpha/<week>` | All bowlers alphabetical with YTD stats and handicap; week selector; printable landscape |
| YTD Alpha | `/reports/season/<id>/ytd-alpha/<week>` | Same data sorted by average descending with rank; fewer columns |
| Weekly High Avg | `/reports/season/<id>/high-avg/<week>` | Same columns as Weekly Alpha, sorted by average with rank |
| Team Standings | `/reports/season/<id>/standings` | Summary tables (overall, first half, second half) plus week-by-week scoring grid showing A/B matchup points and running totals |
| High Games & Averages | `/reports/season/<id>/high-games` | Average leaders (top 20) and top-10 lists for HG scratch, HG handicap, HS scratch, HS handicap; filterable by minimum games |
| Per-Week Prizes | `/reports/season/<id>/week/<week>/prizes` | Four prize categories (HG scratch, HG handicap, HS scratch, HS handicap) with tie handling; team standings through that week; YTD leaders |
| Bowler Detail | `/reports/season/<id>/bowler/<id>` | Individual bowler week-by-week breakdown |
| Payout Overview | `/payout/season/<id>` | YTD prize counts per bowler, weekly prize history, Iron Man candidates, Most Improved |

### Print Batch
A single page (`/reports/season/<id>/print-batch/<week>`) assembles all weekly print materials with three print buttons:

- **Print Group 1** — 4 copies of Weekly Alpha (hand-in score sheets)
- **Print Group 2** — Weekly Alpha + YTD Alpha + Weekly High Avg + High Games (report copies)
- **Print All** — all 8 pages in one job

All pages use landscape layout with tight margins and small font, designed to fit on a single printed page each. Group isolation uses a CSS/JS body-class technique so only the selected group appears in the print job.

### Administration
- Season creation with configurable weeks, half-boundary week, handicap base/factor, and blind score defaults
- Team and roster management; bowlers persist across seasons with carried-over handicap
- Week management: set dates, mark position nights, mark cancellations
- Schedule setup: lane pair assignments per week
- Assign Matchups tool: for each week, manually assign bowlers to lane pair A or B — useful when correcting historical data

## Data Model

```
Season  ──< Team ──< Roster ──> Bowler
        ──< Week
        ──< ScheduleEntry   (which teams bowl which matchup each week)
        ──< MatchupEntry    (one bowler's scores for one matchup)
        ──< TeamPoints      (points earned per team per matchup)
        ──< Snapshot        (weekly JSON snapshot for backup)
```

All statistics (averages, handicaps, high games, standings) are computed on the fly from `MatchupEntry` rows. Nothing derived is stored.

### Key model fields

**MatchupEntry** — one bowler's session for one matchup:
- `game1`–`game3`: primary night scores
- `game4`–`game6`: second-night scores (legacy double-header support)
- `is_blind`: absent bowler placeholder; uses season's `blind_scratch` and `blind_handicap`
- `matchup_num` (1–4): which lane pair this bowler was on

**TeamPoints** — one row per team per matchup per week; `points_earned` is Float to support 0.5-point ties.

## Tech Stack

- **Python 3** / **Flask** — web framework and routing
- **SQLAlchemy** — ORM; SQLite database stored in OneDrive folder for automatic cloud backup
- **Jinja2** — templating (note: `enumerate` is registered as a global function, not a filter)
- **Bootstrap 5** — responsive layout and print utilities
- No JavaScript frameworks — minimal JS for print group isolation and week selector navigation

## Project Layout

```
bowling-league-tracker/
├── app.py                  # App factory, blueprint registration
├── config.py               # DB path (OneDrive-backed), snapshot dir
├── models.py               # SQLAlchemy models
├── calculations.py         # All stat computation (pure functions, no DB writes)
├── snapshots.py            # Weekly JSON snapshot writer
├── routes/
│   ├── admin.py            # Season, team, roster, week, schedule management
│   ├── entry.py            # Score entry, matchup forms, points calculation
│   ├── reports.py          # All report views
│   └── payout.py           # Prize payout overview
├── templates/
│   ├── base.html
│   ├── admin/              # Season/roster/schedule admin pages
│   ├── entry/              # Score entry pages
│   ├── reports/            # Report and print pages
│   └── payout/
└── seed_*.py               # One-time data import scripts (historical XLS import)
```

## Setup

### Requirements

```
flask
flask-sqlalchemy
openpyxl          # only needed for the seed import scripts
```

Install:
```bash
pip install flask flask-sqlalchemy openpyxl
```

### Running

```bash
python app.py
```

The app runs on port 5001 by default. The SQLite database is created automatically on first run, placed in the OneDrive-backed folder if available, otherwise in a local `data/` directory.

### Database initialization

On first run with an empty database, go to `/admin/seasons` to create a season, then set up teams, roster, and schedule before entering scores.

To import from an existing Excel workbook, see the `seed_*.py` scripts — these are one-time use scripts written for a specific workbook format and will need adaptation for other leagues.

## Configuring for a Different League

The application is generic — the league name shown in report headers is hardcoded in the templates and can be changed by editing the string `Mountain Lakes Men's Bowling League` in the relevant templates. All other configuration (team count, number of weeks, handicap formula, blind scores) is per-season in the admin UI.

The handicap formula defaults (base 200, factor 0.9, 3-game series) are set at season creation and can be adjusted for different league rules.

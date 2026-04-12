# Bowling League Tracker — Project Context

## Overview

**Mountain Lakes Men's Bowling League** season tracker. The existing source of truth is an Excel workbook — analyzed but not committed (contains personal info). This project replaces it with a proper web application.

Season: 22 regular weeks + 4 post-season tournament weeks = 26 total. Currently in season 2025-2026.
Teams: 4. Bowlers: ~65 total (mix of active and inactive).

**Important:** Never put player names, team names (which are player surnames), or any other personal information in the repository, code, comments, or documentation.

## Repo / Branch State (as of 2026-04-11)

- GitHub: `dglcinc/bowling-league-tracker` (private)
- Local clone: `~/github/bowling-league-tracker`
- No open PRs — PRs #37–#41 all merged to main

## League Structure

### Weekly Format
- 4 matchups per week, each on one pair of lanes (1 score sheet per lane pair)
- Each team is split across 2 of the 4 matchups simultaneously
- Each matchup: 2 teams, up to 3 games (series), scored on a physical score sheet

### Score Sheet
- Two columns: one team per side
- Teams must have equal player count per lane — if short, add a **blind** (scratch=125, hcp=60 per game, configurable per season)
- 6 game slots per player per week: games 1–3 = primary session, games 4–6 = legacy second session (only top 3 used now)
- Blind entry is a dropdown option (`value="BLIND"`) in the bowler selector; auto-fills scratch scores

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

### Post-Season Tournaments (weeks 23–26)
Four tournament weeks are appended after every regular season. The order is the default; can be reordered via Admin → Week Dates without structural changes.

- **Club Championship** (`tournament_type='club_championship'`, `is_position_night=True`): team competition scored as a position night; uses normal matchup entry; auto-assigns lane assignments from standings
- **Harry E. Russell Championship** (`indiv_scratch`): individual scratch, 5 games; shows all bowlers (active + inactive) + write-in option for non-league participants
- **Hcp Tournament 1** (`indiv_hcp_1`): individual handicap, 3 games; active bowlers + write-in (named "Buz Bedford Championship" pre-2023, "Shep Belyea Open" 2023+)
- **Hcp Tournament 2** (`indiv_hcp_2`): individual handicap, 3 games; active bowlers + write-in (named "Rose Bowl" pre-2023, "Chad Harris Memorial Bowl" 2023+)

Tournament display names are configurable per season via Admin → Week Dates and stored as JSON in `Season.tournament_labels`. Tournament scores stored in `tournament_entries` table (game1=300/200/100 for placement ordering on the prizes page). All tournament weeks excluded from `get_bowler_entries` so they never affect season averages/handicaps. Tournament entry form shows live JS rankings. Top-3 placement can also be set via Admin → Tournament Placements (uses dummy scores 300/200/100).

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
- **seasons**: id, name, start_date, num_weeks, half_boundary_week (default 11), handicap_base (200), handicap_factor (0.9), blind_scratch (125), blind_handicap (60), is_active, bowling_format ('single'/'double'), venue ('mountain_lakes_club' pre-2024-2025, 'boonton_lanes' 2024-2025+), tournament_labels (JSON dict mapping internal key → display name)
- **teams**: id, season_id, number (1–4), name
- **roster**: bowler_id, season_id, team_id, active, prior_handicap, joined_week
- **schedule**: season_id, week_num, matchup_num (1–4), team1_id, team2_id, lane_pair
- **weeks**: season_id, week_num, date, is_position_night, is_cancelled, is_entered, notes, tournament_type
- **matchup_entries**: season_id, week_num, matchup_num, team_id, bowler_id, is_blind, lane_side (A/B), game1–game6
- **team_points**: season_id, week_num, matchup_num, team_id, points_earned (Float — supports 0.5-pt ties)
- **tournament_entries**: season_id, week_num, bowler_id (nullable), guest_name (nullable), game1–game5, handicap
- **snapshots**: season_id, week_num, snapshot_json, created_at

### Key notes
- `MatchupEntry.matchup_num` (1–4) identifies which lane pair — critical for correct scoring; historical data required manual assignment via admin Assign Matchups tool
- `TeamPoints.points_earned` is Float to handle tied games (0.5 pts each)
- `Season.bowling_format`: `'single'` (G1–G3, 8 lanes) or `'double'` (G1–G6, 4 lanes). Both current seasons are 'single'.
- DB migration runs on every startup via `_migrate_db()` in `app.py` — safe to re-run (try/except on ALTER TABLE). Also backfills post-season weeks for seasons where `max(week_num) == num_weeks`.

## Application Structure

### Stack
- Python 3 / Flask (port 5001), SQLAlchemy, SQLite
- Bootstrap 5, Jinja2 — no JS frameworks
- DB stored in OneDrive for auto-backup (see `config.py`); falls back to local `data/`
- `enumerate` registered as a Jinja2 global function — use `enumerate(x)`, NOT `x | enumerate`

### Routes / Blueprints

**`entry_bp`** (`/entry/season/<id>/...`)
- `week_list` — pick a week to enter; shows cancel/uncancel toggle per row
- `week_entry` — week summary with matchup cards, recon totals, prize results; cancel/uncancel button
- `matchup_entry` — score entry form for one lane pair; saves points on POST; triggers position night auto-assignment; blind via dropdown; G4–G6 hidden for 'single' format
- `reconcile` — blind reconciliation view
- `toggle_cancelled` — POST to cancel/uncancel a week
- `tournament_entry` — individual tournament score entry (Harry Russell/Chad Harris/Shep Belyea); live JS rankings

**`reports_bp`** (`/reports/season/<id>/...`)
- `wkly_alpha` — alphabetical roster with YTD stats, printable landscape
- `ytd_alpha` — sorted by average descending, YTD column set
- `wkly_high_avg` — same columns as wkly_alpha, sorted by average with rank
- `standings` — summary tables + week-by-week scoring grid (A/B pts per team, cumulative)
- `high_games` — average leaders + top-10 HG/HS scratch & hcp; `?min_games=N` filter
- `bowler_detail` — full season week-by-week for one bowler; includes venue badge per season
- `week_prizes` — per-week prize winners (4 categories with ties), team standings, YTD leaders; first-half/second-half/season points winners highlighted yellow
- `print_batch` — combined print page: Group 1 = 4× wkly alpha; Group 2 = alpha + YTD + high avg + high games
- `team_points` — season points totals table

**`records_bp`** (`/records`, `/bowler_dir`)
- `records` — all-time leaderboards, season comparison, tournament winners by year, most improved; venue filter (`?venue=all/mountain_lakes_club/boonton_lanes`); tab state persisted via URL hash
- `bowler_dir` — alphabetical list of all bowlers with career highlights and season badges

**`admin_bp`** (`/admin/...`)
- Season, team, roster, week, and schedule management
- `edit_weeks` — set dates (with JS cascade +7 days), position night flags, tournament types, venue, tournament display names
- `tournament_placement` — set 1st/2nd/3rd place finishers per individual tournament; stores dummy scores 300/200/100 in tournament_entries
- `all_bowlers` — lists every bowler across all seasons with season badges and edit links
- `import_season` — web UI to upload XLS and seed a full historical season
- `assign_matchups_list` / `assign_matchups` — per-week tool to assign bowlers to lane pair A or B
- `edit_team` — edit team name and captain name (`Team.captain_name` column); team badges on season_detail are clickable links to this page
- Edit Bowler and Edit Roster are separate buttons on the roster list; edit_bowler no longer includes roster fields

**`payout_bp`** (`/payout/season/<id>`)
- `payout_overview` — YTD prize counts per bowler, weekly prize history, Most Improved
- `payout_config` — Admin: configure PayoutConfig (total available, tournament/weekly/YTD rates, trophy cost, team pct splits)
- `payout_summary` — Totals sheet: individual payouts, team payouts, currency breakdown (bill inventory)
- `award_page` — Per-recipient printable award certificate (guilloche SVG border, Playfair Display/Lato fonts, navy/gold); one page per individual or team
- `PayoutConfig` model: one row per season; waterfall: tournament prizes → weekly wins → YTD prizes → trophy deduction → team remainder by place %

### Print batch groups
- **Group 1 (4 pages)**: 4 copies of Weekly Alpha — the physical hand-in score sheets
- **Group 2 (4 pages)**: Weekly Alpha + YTD Alpha + Weekly High Avg + High Games — report copies
- JS body-class technique isolates groups: `printGroup(n)` sets `print-group-N` on body, CSS hides the other group

### Snapshots
Written automatically after each week is fully entered. Stored as JSON at OneDrive path next to the DB.

## Current State (as of 2026-04-12)

### Seasons in DB
- **2017-2018 through 2023-2024** (historical, venue=mountain_lakes_club): imported via `seed_historical_seasons.py`; regular scores + tournament 1st/2nd/3rd place entries
- **2024-2025** (historical, venue=boonton_lanes): imported via `seed_historical_seasons.py`
- **2025-2026** (active, venue=boonton_lanes): all 22 regular weeks entered; 4 post-season tournament weeks (23–26) added; TeamPoints from spreadsheet
- **2026-2027** (inactive, venue=boonton_lanes): roster seeded from `seed_from_xls.py`; schedule seeded from `seed_schedule.py`; 4 post-season tournament weeks (23–26) added

All seasons have 26 weeks: 22 regular + Club Championship (23), Harry Russell/indiv_scratch (24), indiv_hcp_1 (25), indiv_hcp_2 (26). 2019-2020 is a COVID season with no tournament weeks.

### Seed scripts (run on Mac, Flask app stopped)
XLS path: `~/OneDrive - DGLC/Claude/Historic Scoresheets/`

| Script | Purpose |
|--------|---------|
| `seed_from_xls.py <xlsx>` | Seeds roster + prior handicaps from `wkly alpha` sheet |
| `seed_schedule.py` | Seeds lane-assignment schedule for the active season from DOCX |
| `seed_historical.py <xlsx>` | Seeds 2025-2026 structure: season, teams, bowlers, roster, weeks, schedule |
| `seed_week.py <week_num> <xlsx>` | Imports one week's scores + verifies lane assignment; saves JSON snapshot |
| `seed_all_weeks.py` | Runs `seed_historical.py` then `seed_week.py` for weeks 1–21 in sequence |
| `seed_historical_seasons.py` | Imports all 6 historical seasons (2017-2018 through 2024-2025) from XLS; idempotent (skips existing seasons) |
| `backfill_tournament_winners.py` | Re-reads XLS Payout Formula sheets to backfill 2nd/3rd place tournament entries; safe to re-run |
| `crawl_routes.py` | BFS route tester: crawls all GET routes as editor (all 200) and viewer (checks ALLOW/DENY); run after significant changes |

### Known technical notes
- SQLite writes must run natively on Mac (not from VM) — VirtioFS file locking doesn't support SQLite
- `TeamPoints.points_earned` is Float to support 0.5-pt ties from tied games
- Historical data uses `matchup_num = team_number` as a simplification; corrected per-week via Assign Matchups admin tool
- TeamPoints for historical seasons come from the spreadsheet directly, not recomputed from scores
- Viewer permissions stored in `viewer_permissions` table (endpoint → viewer_accessible bool); managed via Admin → Settings

### Deployment

Production is live at **https://mlb.dglc.com** on Mac Mini M4 (`utilityserver@10.0.0.84`). nginx + TLS on Pi (`pi@10.0.0.82`; config: `/etc/nginx/sites-available/mlb.dglc.com`). App: gunicorn via launchd (`com.dglc.bowling-app`), binds `0.0.0.0:5001`. DB: `~/bowling-data/league.db` (local — NOT OneDrive; SQLite + cloud sync = corruption risk). Restart: `pkill -f "gunicorn.*wsgi"` (launchd auto-restarts). Logs: `/tmp/bowling-app.log`. Full setup guide in `DEPLOYMENT.md` (gitignored).

### Push notifications
- `PushSubscription` model + `push_subscriptions` table (endpoint, subscription JSON, platform, 3 preference booleans)
- `/m/push/subscribe`, `/m/push/unsubscribe`, `/m/push/preferences`, `/m/push/vapid-public-key` routes
- `send_notifications.py` — standalone sender, three triggers: bowling_tomorrow (6 PM prior evening), bowling_tonight (9 AM bowl day), scores_posted (after `week.is_entered`). Per-week `notif_*_sent` flags prevent duplicates.
- `com.dglc.bowling-notify` launchd timer on utilityserver, 10-min interval
- VAPID keys in `.env` (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_PEM`, `VAPID_CLAIMS_EMAIL`) — never change after first subscriber
- Me tab: iOS install prompt → permission button → preference toggles (bowling tomorrow / tonight / scores)

### Still to build
- Season rollover wizard

## Git Workflow

CLAUDE.md pushes directly to main. All other code and documentation changes use feature branches + PRs. See global CLAUDE.md for full workflow.

For `gh` CLI: token is embedded in the remote URL — prefix commands with:
```bash
GITHUB_TOKEN=$(git remote get-url origin | sed 's/.*:\(.*\)@.*/\1/')
```

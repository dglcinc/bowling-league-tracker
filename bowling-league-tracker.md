# Bowling League Tracker — Session Context

## How to Load This Context

Tell Claude: "set context bowling-league-tracker"

Claude will:
1. Read this file
2. Read `~/github/bowling-league-tracker/CLAUDE.md` for the full data model and current state
3. Confirm context loaded and wait for instructions

## Project Location

- Repo: `dglcinc/bowling-league-tracker` (private, GitHub)
- Local clone: `~/github/bowling-league-tracker`

## What This Project Is

A Flask web app replacing the Mountain Lakes Men's Bowling League Excel scoring workbook.
Full stack: Python 3 / Flask / SQLAlchemy / SQLite, Bootstrap 5, Jinja2. No JS frameworks.

## Key Facts

- 26-week season (22 regular + 4 post-season tournaments), ~65 bowlers, 4 teams
- Handicap: `ROUND((200 - prior_week_avg) * 0.9)` for established bowlers (≥6 games)
- All stats computed on the fly from raw `MatchupEntry` rows — nothing derived stored

## SSH to Production

**`ssh utilityserver@10.0.0.84`** — always this exact string. Never `david@` or any other username.

## Production Deployment (live as of 2026-04-11)

- URL: https://mlb.dglc.com
- Server: Mac Mini M4, `utilityserver@10.0.0.84`
- nginx reverse proxy + TLS: Pi at `pi@10.0.0.82`
- App: gunicorn via launchd (`com.dglc.bowling-app`), binds `0.0.0.0:5001`
- DB: `~/bowling-data/league.db` (local on utilityserver — NOT OneDrive; SQLite + cloud sync = corruption risk; backups handle redundancy)
- Restart: `pkill -f "gunicorn.*wsgi"` (launchd auto-restarts)
- Logs: `/tmp/bowling-app.log`, `/tmp/bowling-app.err`

## Current State (as of 2026-04-20)

- PRs #37–#108 all merged to main; no open PRs
- Mobile PWA complete; push notifications deployed (PR #65); admin UI overhauled (PRs #66–#67)
- Historical import (PRs #68–#69): 13 seasons imported (2004-2005 through 2016-2017)
- Tournament data corrections (PRs #70–#73): bulk email, placement fixes, historical tournament winner repair
- Bowler merges + tournament year shift (PR #75): duplicates merged; names corrected; all tournament placement entries shifted one year earlier; 2003-04 stub season created (id=23)
- UI improvements + club championship (PR #76): ClubChampionshipResult model + admin entry; sortable column headers; Flask-Caching on Records and Bowler Directory
- Post-season score entry fixes (PRs #82–#83): null team guards; season selector admin URL fix
- Sortable columns extended (PRs #84, #86); club championship finalists rule (PR #85); Records champion fix (PR #87)
- All 20 historical seasons imported (2004-2005 through 2024-2025); 2025-2026 active (all 22 regular weeks entered, 4 post-season tournament weeks added); 2026-2027 seeded (roster + schedule)
- Cloudflare Turnstile CAPTCHA + WebAuthn passkey support; VAPID/.env docs (PRs #88–#90, #92)
- Invite email flow fixed: OTP removed from invite, users directed to login page instead (PR #90)
- Bulk invite timeout fixed: MSAL app instance cached to avoid per-email token re-acquisition (PR #91)
- Auto-BCC admin on multi-recipient emails; pull-to-refresh on mobile; activity log (PR #92)
- Tournament entry overhaul (PR #108): Harry Russell dropdown shows qualifiers-only in main list + Past Champions optgroup for all-time winners not currently qualifying; `get_hr_qualifiers()` and `get_hr_past_champions()` shared in `calculations.py`; matchup buttons suppressed on individual tournament week_entry pages; 10 default rows on HR entry; desktop home shows qualifiers list matching mobile
- Next: season rollover wizard

## Git Workflow

CLAUDE.md pushes directly to main. All other code and documentation changes use feature branches + PRs. See global CLAUDE.md for full workflow.

For `gh` CLI: token is embedded in the remote URL — prefix commands with:
```bash
GITHUB_TOKEN=$(git remote get-url origin | sed 's/.*:\(.*\)@.*/\1/')
```

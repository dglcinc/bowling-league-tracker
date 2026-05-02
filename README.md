# Bowling League Tracker

A Flask web application for managing a recreational ten-pin bowling league. Replaces a hand-maintained Excel workbook with a proper application for score entry, handicap calculation, standings, prize tracking, and printable weekly reports. This is for a specific league that bowls on 8 lanes with some hard-coded post season tournaments. You can fork and modify for your own league. The advantage of this app rather than using the standard league software at the alley is you can have bowlers come and go week to week and bowl on different lanes, so it's more flexible and chill. The alley we go to runs the lanes with league format (two lane matches with lane swaps each frame) but it allows us to enter bowlers free-form each week. It also has weekly and year end prizes for both individuals and teams, with a calculator to divvy up a pool of money. The spreadsheet import will not do you any good, it's very specific to a highly curated spreadsheet we used before this app was built.

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
| Club Team Championship (`club_championship`) | Team competition, position-night scoring | Uses standard matchup entry; lane assignments auto-assigned from standings |
| Individual Scratch Championship (`indiv_scratch`) | Individual, 5-game scratch | Top-10 average qualifiers (≥30 games) in main dropdown; all-time past champions in a separate optgroup; write-in option for non-league participants |
| Individual Handicap 1 (`indiv_hcp_1`) | Individual, 3-game handicap | Active bowlers + write-in |
| Individual Handicap 2 (`indiv_hcp_2`) | Individual, 3-game handicap | Active bowlers + write-in |

Tournament display names are configurable per season in Admin → Week Dates and stored as JSON in the `Season` row, so the same tournament types can carry different names across seasons without code changes.

The individual tournament entry form shows live rankings that update as scores are typed.

### Authentication and Access Control
The app uses passwordless authentication — no passwords stored.

- **Magic links**: bowlers request a sign-in link by email; the link is single-use and expires in 24 hours
- **Passkeys**: after signing in, bowlers can register a passkey (Touch ID, Face ID, or hardware key) for one-tap sign-in
- **Two roles**: `editor` (full access to score entry and admin) and `viewer` (read-only access to configurable subset of pages)
- **Viewer permissions**: admin UI at `/admin/viewer-access` controls which pages viewer-role users can reach
- **Cloudflare Turnstile**: optional bot protection on the login page (configure `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` in `.env`; skipped in dev if keys are absent)
- **Rate limiting**: login endpoint is rate-limited via Flask-Limiter

Admin can send magic links in bulk to all bowlers on a season from the season detail page.

### End-of-Season Payout
Full payout calculator with printable output for the end-of-season banquet.

- **Config**: admin sets total available funds and configures prize rates (tournament places, weekly wins, YTD categories, trophy deduction, team place percentages)
- **Waterfall calculation**: tournament awards → weekly/YTD individual prizes → trophy deduction → team remainder distributed by place finish
- **Payout summary**: three-section printable totals sheet — individual payouts (itemized), team payouts by place, and a currency breakdown showing exact bill inventory to pull from the bank
- **Award pages**: one printable certificate per recipient, designed for handing out at the banquet (ornamental border, formal typography)

### Reports

| Report | URL | Description |
|--------|-----|-------------|
| Weekly Alpha | `/reports/season/<id>/alpha/<week>` | All bowlers alphabetical with YTD stats and handicap; week selector; printable landscape |
| YTD Alpha | `/reports/season/<id>/ytd-alpha/<week>` | Same data sorted by average descending with rank; fewer columns |
| Weekly High Avg | `/reports/season/<id>/high-avg/<week>` | Same columns as Weekly Alpha, sorted by average with rank |
| Team Standings | `/reports/season/<id>/standings` | Summary tables (overall, first half, second half) plus week-by-week scoring grid |
| High Games & Averages | `/reports/season/<id>/high-games` | Average leaders and top-10 lists for HG/HS scratch and handicap; filterable by minimum games |
| Per-Week Prizes | `/reports/season/<id>/week/<week>/prizes` | Four prize categories with tie handling; team standings; YTD leaders |
| Bowler Detail | `/reports/season/<id>/bowler/<id>` | Individual bowler week-by-week breakdown; clicking any score navigates to the detail page for that week |
| All-Time Records | `/records` | All-time leaderboards, season comparison table, tournament winners by year, Most Improved, Fun Stats, and an Ask (LLM) tab. Venue filter available. Sortable columns throughout. |
| Bowler Directory | `/bowler_dir` | All bowlers with career highlights and season badges |
| Payout Overview | `/payout/season/<id>` | YTD prize counts, weekly prize history, Most Improved |
| Payout Summary | `/payout/season/<id>/summary` | Full end-of-season payout calculation with currency breakdown |
| Award Pages | `/payout/season/<id>/award/all` | Printable award certificates for all recipients |

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
- League Settings (`/admin/settings`): configure league name, nickname display, and captain name display
- Viewer Permissions (`/admin/viewer-access`): control which pages viewer-role users can access
- Payout Config: linked from each season's admin page; set prize rates before running the end-of-season payout
- Send Magic Links: bulk-send sign-in email invitations to all bowlers on a season
- Mailing List: export or email a weekly results summary to the season's roster

### PWA / Mobile App
The app ships a web app manifest and service worker so it can be installed as a Progressive Web App on iOS, Android, and desktop Chrome. The home screen icon is a 🎳 emoji rendered at full resolution.

The `/m/` mobile route set provides a phone-optimised home page showing: upcoming lane assignments, last week's results (score, opponent points, standings delta), current standings, and individual bowler stats. It detects mobile user agents and redirects automatically.

**Push notifications** (Web Push / VAPID) are supported on the mobile home page. Bowlers can enable per-event preferences for three notification types: the evening before bowling night, the morning of bowling night, and when scores are posted. Notification sending is handled by `send_notifications.py`, run on a 10-minute launchd timer.

## Data Model

```
Season  ──< Team ──< Roster ──> Bowler
        ──< Week
        ──< ScheduleEntry     (which teams bowl which matchup each week)
        ──< MatchupEntry      (one bowler's scores for one matchup)
        ──< TeamPoints        (points earned per team per matchup)
        ──< TournamentEntry   (individual tournament scores, not in season stats)
        ──< PayoutConfig      (end-of-season prize configuration)
        ──< Snapshot          (weekly JSON snapshot for backup)

LeagueSettings               (single row — league name, display options)
MagicLinkToken ──> Bowler    (single-use sign-in tokens)
LinkedAccount  ──> Bowler    (tracks auth method per bowler)
WebAuthnCredential ──> Bowler (registered passkeys)
ViewerPermission             (per-endpoint viewer access flags)
```

All statistics (averages, handicaps, high games, standings) are computed on the fly from `MatchupEntry` rows. Nothing derived is stored.

### Key model fields

**Season** — `bowling_format`: `'single'` (G1–G3, 8 lanes) or `'double'` (G1–G6, 4 lanes).

**Week** — `tournament_type`: null for regular weeks; `'club_championship'`, `'indiv_scratch'`, `'indiv_hcp_1'`, or `'indiv_hcp_2'` for post-season weeks. Display names are stored separately in `Season.tournament_labels` (JSON).

**MatchupEntry** — one bowler's session for one matchup:
- `game1`–`game3`: primary night scores
- `game4`–`game6`: second-night scores (double-night format)
- `is_blind`: absent bowler placeholder; uses season's `blind_scratch` and `blind_handicap`
- `matchup_num` (1–4): which lane pair this bowler was on

**TournamentEntry** — individual tournament score; `bowler_id` is nullable (write-in participants use `guest_name` instead).

**TeamPoints** — `points_earned` is Float to support 0.5-point ties.

**PayoutConfig** — one row per season; stores all prize rates, team payout percentages, and final week number for the payout calculation.

## Tech Stack

- **Python 3** / **Flask** — web framework and routing (port 5001)
- **SQLAlchemy** — ORM; SQLite database
- **Flask-Login** — session management and user authentication
- **Flask-Limiter** / **Flask-Caching** — rate limiting on auth endpoints; page-level caching for Records and Bowler Directory
- **Jinja2** — templating
- **Bootstrap 5** — responsive layout and print utilities
- **MSAL + Microsoft Graph API** — email delivery via Microsoft 365; uses client credentials flow (no SMTP)
- **python-webauthn** — passkey/WebAuthn registration and authentication
- **py_vapid / pywebpush** — Web Push / VAPID for PWA push notifications
- **WeasyPrint** — PDF generation for weekly prizes email attachment (optional; requires system Pango library)
- **python-dotenv** — `.env` file support for local development
- No JavaScript frameworks — vanilla JS for blind auto-fill, date cascade, live tournament rankings, sortable tables, and print group isolation

## Project Layout

```
bowling-league-tracker/
├── app.py                  # App factory, blueprint registration, DB migration, home page
├── config.py               # DB path, snapshot dir
├── extensions.py           # Shared Flask extensions (db, login_manager, limiter, cache)
├── models.py               # SQLAlchemy models
├── calculations.py         # All stat computation (pure functions, no DB writes)
│                           #   Shared helpers: entry_handicap, entry_total_wood,
│                           #   get_bowler_entries_bulk, build_leaders_list,
│                           #   get_latest_entered_week, auto_assign_position_night
├── snapshots.py            # Weekly JSON snapshot writer
├── send_notifications.py   # Web Push sender (bowling_tomorrow / tonight / scores_posted)
├── routes/
│   ├── admin.py            # Season, team, roster, week, schedule, XLS import, email, PDF
│   ├── auth.py             # Login, magic link, passkey (WebAuthn), logout
│   ├── entry.py            # Score entry, matchup forms, tournament entry, points calculation
│   ├── mobile.py           # Mobile/PWA home, standings, scores, push subscription
│   ├── records.py          # All-time records, bowler directory, stat builder
│   ├── reports.py          # Weekly/YTD reports, print batch, high games, prizes, standings
│   └── payout.py           # Prize payout overview, config, summary, award pages
├── static/
│   ├── manifest.json       # PWA manifest
│   ├── sw.js               # Service worker
│   └── icons/              # PWA icons (192px, 512px)
├── templates/
│   ├── base.html
│   ├── admin/              # Season/roster/schedule/settings admin pages
│   ├── auth/               # Login and passkey management pages
│   ├── entry/              # Score entry and tournament entry pages
│   ├── mobile/             # Mobile PWA pages
│   ├── records/            # All-time records and bowler directory
│   ├── reports/            # Report and print pages
│   └── payout/             # Payout config, summary, and award certificate pages
└── seed_*.py               # One-time data import scripts (historical XLS import)
```

## Setup

### Requirements

```
flask>=3.0.0
flask-sqlalchemy>=3.1.0
flask-login>=0.6.3
flask-limiter>=3.5.0
flask-caching>=2.1.0
python-dotenv>=1.0.0
openpyxl>=3.1.0
weasyprint>=62.0
msal>=1.29.0
webauthn>=2.0.0
py-vapid>=1.9.0
pywebpush>=2.0.0
```

Install:
```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```bash
# Microsoft Graph API (email delivery)
GRAPH_TENANT_ID=your-tenant-id
GRAPH_CLIENT_ID=your-client-id
GRAPH_CLIENT_SECRET=your-client-secret
GRAPH_SENDER_EMAIL=sender@yourdomain.com

# Cloudflare Turnstile (optional bot protection on login page)
TURNSTILE_SITE_KEY=your-site-key
TURNSTILE_SECRET_KEY=your-secret-key

# Web Push / VAPID (required for push notifications)
# Generate once with: python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print(v.public_key, v.private_key)"
# Do NOT rotate after the first subscriber — existing subscriptions will break
VAPID_PUBLIC_KEY=your-vapid-public-key
VAPID_PRIVATE_PEM=your-vapid-private-key-pem
VAPID_CLAIMS_EMAIL=mailto:admin@yourdomain.com

# WeasyPrint on Apple Silicon (if using PDF generation)
DYLD_LIBRARY_PATH=/opt/homebrew/lib

# Flask secret key
SECRET_KEY=a-long-random-string
```

Email delivery requires an Azure AD app registration with `Mail.Send` permission using client credentials flow. If Graph API credentials are not configured, magic link emails will fail silently in development — use `gen_magic_link.py` to generate a link directly from the command line.

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
5. Configure league name and display options at `/admin/settings`

Four post-season tournament weeks are created automatically; their order can be adjusted by changing the tournament type dropdown in Week Dates.

### Importing a historical season

Use `/admin/import_season` to upload an existing Excel workbook. The import reads `wkly alpha` for roster, individual bowler sheets for game scores, and `team scoring` for team standings.

### WeasyPrint on Apple Silicon

WeasyPrint requires the Pango text rendering library. On an Apple Silicon Mac:

```bash
brew install pango
# Create Linux-compatible symlinks expected by WeasyPrint
ln -s /opt/homebrew/lib/libpango-1.0.dylib /opt/homebrew/lib/libpango-1.0.so.0
# (repeat for other Pango/Cairo libs as needed)
```

Set `DYLD_LIBRARY_PATH=/opt/homebrew/lib` in your `.env`.

## Configuring for a Different League

All configuration (team count, number of weeks, handicap formula, blind scores, bowling format) is per-season in the admin UI. The handicap formula defaults (base 200, factor 0.9) can be adjusted for different league rules. League name and display options are in Admin → League Settings.

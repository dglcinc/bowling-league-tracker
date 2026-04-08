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

## Installation & Deployment

### 1. Prerequisites

Install [Homebrew](https://brew.sh) if not already present, then install system libraries required by WeasyPrint (PDF generation) and create symlinks so WeasyPrint can find them by the Linux-style names it expects:

```bash
brew install pango
sudo ln -sf /opt/homebrew/lib/libgobject-2.0.0.dylib   /usr/local/lib/libgobject-2.0-0.dylib
sudo ln -sf /opt/homebrew/lib/libpango-1.0.0.dylib      /usr/local/lib/libpango-1.0.0.dylib
sudo ln -sf /opt/homebrew/lib/libpangocairo-1.0.0.dylib /usr/local/lib/libpangocairo-1.0.0.dylib
sudo ln -sf /opt/homebrew/lib/libcairo.2.dylib          /usr/local/lib/libcairo.2.dylib
```

> **Why symlinks?** WeasyPrint uses Linux library names (e.g. `libgobject-2.0-0`) but macOS Homebrew installs them with different names (e.g. `libgobject-2.0.0.dylib`). Setting `DYLD_LIBRARY_PATH` does not fix this because the filename mismatch means the linker still can't match the name WeasyPrint requests.

Verify Python 3.11 or later is available:

```bash
python3 --version
```

### 2. Clone the repository

```bash
git clone https://github.com/dglcinc/bowling-league-tracker.git
cd bowling-league-tracker
```

### 3. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

Dependencies installed:
- `flask` — web framework
- `flask-sqlalchemy` — ORM / SQLite
- `flask-mail` — outbound email via Exchange SMTP
- `python-dotenv` — loads secrets from `.env` file
- `openpyxl` — XLS import
- `weasyprint` — PDF generation for email attachments and print batch

### 4. Configure secrets

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```
SECRET_KEY=<any-long-random-string>

MAIL_SERVER=smtp.office365.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=you@yourdomain.com
MAIL_PASSWORD=<exchange-app-password>
MAIL_DEFAULT_SENDER=you@yourdomain.com
```

`MAIL_PASSWORD` must be an **app password**, not your main account password. Create one in your Microsoft account security settings under **Security → Advanced security options → App passwords**.

### 5. Enable SMTP AUTH in Microsoft 365

Two settings must be changed — both are required:

**Step A: Disable Security Defaults in Azure AD**

Security Defaults blocks all basic/legacy authentication (including SMTP AUTH) tenant-wide.

1. Go to [portal.azure.com](https://portal.azure.com)
2. **Azure Active Directory → Properties → Manage Security Defaults**
3. Set **Enable Security Defaults** to **No** → Save

**Step B: Enable Authenticated SMTP for your mailbox**

1. Sign in to [Microsoft 365 Admin Center](https://admin.microsoft.com)
2. Go to **Users → Active users** → click your account
3. Open the **Mail** tab → **Manage email apps**
4. Check **Authenticated SMTP** → Save

Both steps are required. Step A alone won't work, and Step B has no effect while Security Defaults is on.

### 6. Run the app

```bash
python3 app.py
```

The app starts on **port 5001**. Open `http://localhost:5001` in a browser.

The SQLite database is created automatically on first run. It is stored in `~/OneDrive - DGLC/Claude/bowling-league-tracker/league.db` if that path is available, otherwise in a local `data/` directory. Automatic backups are written to a `backups/` subfolder next to the database after every write.

### 7. Running as a background service (headless Mac)

To start the app automatically at login on a headless Mac Mini, create a launchd plist:

```bash
mkdir -p ~/Library/LaunchAgents
```

Create `~/Library/LaunchAgents/com.dglc.bowling-tracker.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dglc.bowling-tracker</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/david/github/bowling-league-tracker/app.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/david/github/bowling-league-tracker</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/david/Library/Logs/bowling-tracker.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/david/Library/Logs/bowling-tracker.log</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.dglc.bowling-tracker.plist
```

To stop/restart:

```bash
launchctl unload ~/Library/LaunchAgents/com.dglc.bowling-tracker.plist
launchctl load   ~/Library/LaunchAgents/com.dglc.bowling-tracker.plist
```

### 8. Remote access via Caddy (optional)

To access the app from outside the local network, set up [Caddy](https://caddyserver.com) as a reverse proxy with automatic HTTPS:

```bash
brew install caddy
```

Create `/usr/local/etc/Caddyfile` (replace with your domain):

```
bowling.yourdomain.com {
    reverse_proxy localhost:5001
}
```

Configure your router to forward ports 80 and 443 to the Mac Mini, then start Caddy:

```bash
brew services start caddy
```

Caddy handles TLS certificates automatically via Let's Encrypt.

---

### First-time data setup

1. Go to **Admin → Seasons → New Season** — set weeks, bowling format, team names, handicap formula
2. Add bowlers under **Admin → Manage** → **+ Add Bowler**
3. Set up weekly lane assignments under **Admin → Schedule**
4. Set week dates under **Admin → Week Dates** — enter the first date; subsequent weeks auto-fill at +7 days
5. Update bowler email addresses under **Admin → Mailing List**

Four post-season tournament weeks are appended automatically.

### Importing a historical season

Use **Admin → Import Season from XLS** to upload an existing Excel workbook. The import reads `wkly alpha` for roster, individual bowler sheets for game scores, and `team scoring` for team standings.

## Configuring for a Different League

All configuration (team count, number of weeks, handicap formula, blind scores, bowling format) is per-season in the admin UI. The handicap formula defaults (base 200, factor 0.9) can be adjusted for different league rules.

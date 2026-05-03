# Bowling League Tracker — Project Context

## Overview

**Mountain Lakes Men's Bowling League** season tracker. The existing source of truth is an Excel workbook — analyzed but not committed (contains personal info). This project replaces it with a proper web application.

Season: 22 regular weeks + 4 post-season tournament weeks = 26 total. Currently in season 2025-2026.
Teams: 4. Bowlers: ~65 total (mix of active and inactive).

**Important:** Never put player names, team names (which are player surnames), or any other personal information in the repository, code, comments, or documentation.

## Repo / Branch State (as of 2026-05-02)

- GitHub: `dglcinc/bowling-league-tracker` (private)
- Local clone: `~/github/bowling-league-tracker`
- No open PRs.
- PRs #37–#141 merged to main; #133 closed unmerged (functionality replaced by `query_db` in #135; tool-schema shape obsoleted by #138).

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
- **Harry E. Russell Championship** (`indiv_scratch`): individual scratch, 5 games; entry dropdown shows top-10 qualifiers (≥30 regular-season games, active rostered, top avg) in the main list + write-in; all-time winners (place=1) who are NOT current qualifiers appear in a "Past Champions" optgroup (covers both rostered-but-below-30-games and un-rostered past winners); entry page starts with 10 rows; desktop and mobile home pages both show qualifiers list when Russell is upcoming. Shared helpers: `get_hr_qualifiers()` and `get_hr_past_champions()` in `calculations.py`.
- **Hcp Tournament 1** (`indiv_hcp_1`): individual handicap, 3 games; active bowlers + write-in (named "Buzz Bedford Championship" pre-2023, "Shep Belyea Open" 2023+)
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
- **tournament_entries**: season_id, week_num, bowler_id (nullable), guest_name (nullable), game1–game5, handicap, place (1/2/3, nullable — set for historical imports)
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
- `bowler_detail` — full season week-by-week for one bowler; includes venue badge per season; week rows have `id="week-N"` anchors for score link deep-linking; breadcrumb shows "Records" when `?back=records` is in URL
- `week_prizes` — per-week prize winners (4 categories with ties), team standings, YTD leaders; first-half/second-half/season points winners highlighted yellow
- `print_batch` — combined print page: Group 1 = 4× wkly alpha; Group 2 = alpha + YTD + high avg + high games
- `team_points` — season points totals table

**`records_bp`** (`/records`, `/bowler_dir`)
- `records` — all-time leaderboards, season comparison, tournament winners by year, most improved; venue filter (`?venue=all/mountain_lakes_club/boonton_lanes`); tab state persisted via URL hash; `?at=top|bottom|all` filter on All-Time tab; Fun Stats tab (lowest avg, most games, most 200+, lowest individual games); Ask tab (LLM stats assistant)
- Score cells throughout are invisible links (`text-decoration-none text-body`) — clicking any score navigates to `bowler_detail` for that season, scrolled to the specific week via `#week-N` anchor. `get_bowler_stats()` now returns `ytd_high_*_week` fields. Pages arrived via score links pass `?back=records`; bowler_detail breadcrumb swaps "Bowler Directory" for "Records" when `back=records` is present.
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
- Season detail All filter: rostered (active or inactive) and unrostered bowlers appear in one unified alphabetical list; unrostered entries show as Inactive with Add to Roster button (no separate section)

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

## Current State (as of 2026-04-20)

### Seasons in DB
- **2004-2005 through 2016-2017** (historical, venue=mountain_lakes_club): imported via `seed_historical_seasons.py`; seasons id=10–22; regular scores + tournament 1st/2nd/3rd place entries with `place` field set
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
| `seed_historical_seasons.py` | Imports all 20 historical seasons (2004-2005 through 2024-2025) from XLS; idempotent (skips existing seasons); new seasons read from `~/OneDrive - DGLC/Claude/Historic Scoresheets/Bowling Spreadsheets/` |
| `backfill_tournament_winners.py` | Re-reads XLS Payout Formula sheets to backfill 2nd/3rd place tournament entries; safe to re-run |
| `crawl_routes.py` | BFS route tester: crawls all GET routes as editor (all 200) and viewer (checks ALLOW/DENY); run after significant changes |

### Known technical notes
- SQLite writes must run natively on Mac (not from VM) — VirtioFS file locking doesn't support SQLite
- `TeamPoints.points_earned` is Float to support 0.5-pt ties from tied games
- Historical data uses `matchup_num = team_number` as a simplification; corrected per-week via Assign Matchups admin tool
- TeamPoints for historical seasons come from the spreadsheet directly, not recomputed from scores
- Viewer permissions stored in `viewer_permissions` table (endpoint → viewer_accessible bool); managed via Admin → Settings
- Post-season `ScheduleEntry` rows can have `team1_id = NULL` / `team2_id = NULL` (club championship uses all 4 teams via position night, no fixed pairing). `score_position_night` skips null-team entries; `position_entry` falls back to all season teams when scheds[0].team1/.team2 are None.
- **Club championship finalists rule**: `tournament_placement` route checks if first-half and second-half points leaders are the same team. If so, that team plays the second-place second-half team (not an automatic win). Otherwise the two half-winners are the finalists.
- **`league_settings` table**: single row (id=1). Contains `prizes_min_games` (INTEGER DEFAULT 9) and `prizes_top10` (BOOLEAN DEFAULT 0). Always update with explicit `db.session.execute(text('UPDATE league_settings SET prizes_min_games=:mg, prizes_top10=:t10 WHERE id=1'), {...})` — SQLAlchemy ORM attribute assignment + commit is unreliable for this table (doesn't mark object dirty).
- **`get_bowler_stats()` key names**: average is `running_avg`, not `current_average`. Games count is `cumulative_games`.
- **`login_manager.login_view = 'auth.login'`** is set in `extensions.py`. Without it, `@login_required` calls `abort(401)` instead of redirecting to the login page. If users report bare 401 pages on login flows, verify this is still set and `auth.login` still resolves.
- **`/healthz`** is the public health probe — no auth, no DB, no `request_log` row. Used by `check_health.py` and `com.dglc.bowling-health` launchd timer. Do NOT route the health check at `/` — that goes through `index()` which redirects unauthenticated callers to `/auth/login`, which polluted the access log with 1,700+ entries per week pre-PR.
- **WebAuthn `authenticate/begin`:`complete` ratio is intentionally lopsided.** `templates/auth/login.html` calls `startConditionalPasskey()` on every login page load — this POSTs `/auth/webauthn/authenticate/begin` to enable passkey autofill mediation, but `complete` only fires if the user actually picks a passkey from the autofill prompt. Most page loads end without a `complete`. This is normal; not a bug.
- **Flask-Limiter storage**: `extensions.py` uses `storage_uri="memory://"`. Each gunicorn worker has its own counter, so the worst-case effective limit per IP is `configured_limit × num_workers` (≈ 2× at current config). Tighten configured limits accordingly, or move to a shared backend (Redis, memcached) if effective limits ever matter.
- **Shared helpers in `calculations.py`** (PR #110): `entry_handicap(entry, season, season_id, week_num, entries_by_bowler=None)` and `entry_total_wood(...)` centralise the blind/non-blind handicap expression. `get_bowler_entries_bulk(bowler_ids, season_id)` pre-fetches season entries for N bowlers in 2 queries (pass result as `entries_by_bowler` to avoid N+1). `build_leaders_list(season_id, through_week, min_games, top10)` returns `(leaders, avg_rows)`. `get_latest_entered_week(season_id, exclude_cancelled=False)` replaces the inline `Week.query.filter_by(is_entered=True)...first()` pattern. `auto_assign_position_night(season_id, week_num)` moved here from `entry.py`.
- **Cache invalidation**: `cache.clear()` must be called after `week.is_entered = True` in every scoring POST (matchup_entry, position_entry, tournament_entry). All three paths do this as of PR #110.
- **Tournament entry dropdown JS**: new rows are created by cloning `firstSelect.innerHTML`, so `<optgroup>` elements added in the Jinja template automatically carry through to dynamically-added rows. New row's bowler-select is reset with `sel.selectedIndex = 0` (PR #114) — don't switch back to `sel.value = ''`, that's brittle when the cloned innerHTML carries a `selected` attribute.
- **Tournament entry row buffer + draft saves** (PR #114): all three `tournament_entry` types (`indiv_scratch`, `indiv_hcp_1`, `indiv_hcp_2`) render `max(existing+5, 10)` rows so there's always headroom to add bowlers. POST handler persists rows that have a bowler/guest_name even when no scores are entered (names-only "draft" save). `week.is_entered` is only set when at least one score is present — names-only saves leave the week in draft state so the "scores posted" push notification doesn't fire prematurely.
- **Email send flow** (`admin/email_compose`): two-step POST — first POST resolves recipients and renders a preview modal; second POST with `send_confirmed=1` actually sends. Preview modal renders **TO / CC / BCC / Body** as editable fields with recipient counts (PR #117); `cc_override` and `bcc_override` textareas let the editor adjust either list at the last step. The `body_text` is now a visible textarea in the preview, not a hidden input — typos can be caught right before send. PDF attachment is the same `reports/week_prizes.html` the navbar serves (PR #116) — both go through `routes.reports.build_week_prizes_context()` so they can never drift; `week_prizes_pdf.html` is gone. Tournament weeks still get the PDF (PR #115 dropped the `not week.tournament_type` guard).
- **`_send_via_graph` signature** (PR #117): `(app_config, subject, html_body, to_list, bcc_list, cc_list=None, pdf_attachment=None, pdf_filename=None)`. `cc_list` is keyword-only-by-convention because it's optional; passes through to Graph as `ccRecipients`.
- **Admin Send Email modal** (`templates/admin/season_detail.html`): Subject prefills with `league_settings.league_name` (PR #117). Different route from the weekly email — `admin.send_email`, ad-hoc, no preview modal.
- **Prizes page / print batch**: prize calculation skipped entirely for tournament weeks (`tournament_type` not None); YTD leaders and high averages are still shown for all weeks including tournament weeks. Print orientation is portrait (`@page { size: portrait }` in `week_prizes.html`).
- **Gunicorn error log**: tracebacks go to `/tmp/bowling-app.err`, not `/tmp/bowling-app.log` (which is stdout/access).
- **Season selector JS** (base.html): admin routes use `/seasons/<id>` (plural, no trailing slash); entry routes use `/season/<id>` (singular, NO trailing slash — week_list is `/entry/season/<id>` with no slash). `replaceSeasonInPath()` uses `(\/|$)` to handle both trailing-slash and end-of-path cases. `onSeasonScopedPage` uses same pattern. Records/BowlerDir pages set `isCrossSeasonPage=true` (via Jinja endpoint check) to suppress stored-season restore. Pages arrived at via `?back=records` set `arrivedFromRecords=true` to skip localStorage update (prevents browsing historical records from corrupting the working season).
- **Sortable columns**: `sortable-head` class on `<thead>`, `data-sort="num"|"text"` on `<th>`, optional `data-sort-val` on `<td>` when display differs from sort value (e.g. medal emoji, "3, 3, 3" games string, score+name cell). Applied to: Weekly Alpha, YTD Alpha, Bowler Directory, Records (All-Time + By Season + Most Improved), Bowler Detail (all 3 tables).
- Records By Season tab: two-row merged header was flattened to single row (required for column-index sort to match td positions). Column labels abbreviated to HG Scr / HG Hcp / HS Scr / HS Hcp.

### Deployment

Production is live at **https://mlb.dglc.com** on Mac Mini M4 (`utilityserver@10.0.0.84`). nginx + TLS on Pi (`pi@10.0.0.82`; config: `/etc/nginx/sites-available/mlb.dglc.com`). App: gunicorn via launchd (`com.dglc.bowling-app`), binds `0.0.0.0:5001`. DB: `~/bowling-data/league.db` (local — NOT OneDrive; SQLite + cloud sync = corruption risk). Restart: `pkill -f "gunicorn.*wsgi"` (launchd auto-restarts). Logs: `/tmp/bowling-app.log`. Full setup guide in `DEPLOYMENT.md` (gitignored).

- SSH username is always `utilityserver` — never `david` or any other name.
- Deploy from dev Mac (single command): `ssh macmini '~/bin/deploy-bowling.sh'`
- `~/bin/deploy-bowling.sh` runs `git checkout main && git pull --ff-only && launchctl restart`. The `checkout main` is deliberate — Ralph loops can leave the working dir on a feature branch, and prior to 2026-05-02 the deploy would happily ship that branch's HEAD to production. Hardened after Ralph's `ralph-finish.sh` accidentally deployed an unmerged stack of 6 PRs.
- Backup: `~/bin/backup-bowling.sh` → `~/bowling-data/backups/`, 3am daily via launchd; 30-day retention.
- Route 53: `~/bin/update-r53.sh`, profile `dglc-admin`, zone `Z0225171IDMZU3O5FZM0`, every 10 min via launchd.
- Health check: `check_health.py` + `com.dglc.bowling-health` launchd timer (5-min interval). Pings `localhost:5001`; emails `david@dglc.com` via Graph API on first failure and again on recovery. Sentinel file `/tmp/bowling-health-down` prevents repeat alerts. Logs: `/tmp/bowling-health.log` / `/tmp/bowling-health.err`.
- **wsgi.py**: gunicorn entrypoint (`from app import create_app; app = create_app()`). Must exist in repo root — plist uses `wsgi:app`. Was lost in a rebase on 2026-04-26 causing a production outage; now tracked in git.

Claude Code runs directly on the production server — do not SSH to `10.0.0.84`, run commands locally.

To reload the launchd plist after editing it directly: `launchctl unload ~/Library/LaunchAgents/com.dglc.bowling-app.plist && launchctl load ~/Library/LaunchAgents/com.dglc.bowling-app.plist`. Needed when plist changes don't take effect on a simple gunicorn restart.

To send email outside the web UI (e.g. an ad-hoc bulk send), wrap the call in `app.test_request_context('/', base_url='https://mlb.dglc.com')` so `url_for(_external=True)` resolves:

```python
from app import create_app
app = create_app()
with app.app_context():
    with app.test_request_context('/', base_url='https://mlb.dglc.com'):
        # call send_otp_invite, send_otp, etc.
```

### Stats assistant (`/chat`, Records → Ask tab)
- **Surface**: standalone page at `/chat` plus an "Ask" tab on `/records` (partial: `templates/reports/chat_panel.html`). Streaming Q&A — type a stats question, watch tokens render live, tool-call disclosure panel shows what the model looked up. Optional press-and-hold mic uses Web Speech API (iOS Safari + Chrome/Edge); hidden where unsupported. Thumbs-up/down POSTs to `POST /chat/feedback`. The mic stop is delayed 350 ms so trailing audio isn't clipped (`templates/reports/chat_panel.html`).
- **Markdown rendering** (PR #139): tokens stream into the answer div as `textContent` so the user sees them appear live; on the SSE `done` event a small inline `renderMarkdown()` function (~30 lines, no deps, HTML-escapes input) swaps `textContent` for `innerHTML`. Handles `**bold**`, `*italic*`, `- ` / `* ` bulleted lists, and `N. ` numbered lists. Function is duplicated in `templates/reports/chat_panel.html` and `templates/chat/index.html` — comments in each point at the other; if it grows much beyond this subset, extract to a shared `static/js/` file.
- **Routes** (`routes/chat.py`, blueprint `chat_bp` at `/chat`): `GET /chat` (page), `POST /chat/ask` (SSE stream — `tool_call` / `token` / `done` / `error` events), `POST /chat/feedback`. All `@login_required`. `chat.ask` is in `viewer_permissions` so viewers see the same UI as editors. Per-IP rate limit on `/chat/ask`: `20/hour;5/minute`.
- **Backend**: Anthropic Claude API via the official `anthropic` SDK (PR #134, deployed 2026-05-02). Default model `claude-haiku-4-5` (switched from Sonnet 4.6 — tools encode the business logic so Haiku is sufficient and ~5× cheaper); override with `CHAT_MODEL` env var. Auth via `ANTHROPIC_API_KEY` in `.env`. Manual streaming loop in `ask()` so per-token streaming + `tool_call` SSE events both work. ~$0.001–0.005 per question on Haiku; system prompt + tool catalog cached via `cache_control` (5-min TTL) so follow-ups in a session pay ~0.1× on the prefix.
- **Architecture: hybrid — focused tools for business rules + `query_db` SQL escape hatch.** The model picks per question. Seven LLM-facing tools in `chat_tools.py`:
    - `bowler_season_stats`, `bowler_career_stats`, `season_leaders`, `all_time_records`, `most_improved`, `weekly_prizes` — wrap helpers in `calculations.py` / `routes/records.py` that encode handicap math, blind-skipping, and tournament-week-from-averages exclusion. Plain SQL on `matchup_entries` would get those wrong.
    - `query_db(sql, params=None)` — read-only SELECT (or `WITH ... SELECT`) for everything else. Validation: single statement, must start with `SELECT` or `WITH`, mutation keywords rejected, auth/log tables denied (`user_account` / `request_log` / `chat_log` / `viewer_permission` / `audit_log` / `payout_config` / `webauthn_credential` / sqlite internals), `PRAGMA query_only=1` set on the connection as defense-in-depth, capped at 200 rows. Schema for the model lives in `SYSTEM_PROMPT`.
- **System prompt**: `SYSTEM_PROMPT` in `routes/chat.py` — league overview + handicap rules + tournament glossary + WHAT-IS-NOT-IN-THE-DATA refusal rule + database schema + when-to-use-which-tool guidance + "make tool calls silently, do not narrate" instruction. ~5K chars; cached.
- **Tool result truncation**: 64 KB per tool call (was 8 KB pre-#135). With `query_db` capped at 200 rows this rarely bites, but it's headroom for future tools.
- **`ChatLog` model** (`chat_log` table): `id, user_id (FK user_account.id, nullable), question_text, answer_text, tool_calls_json, helpful (nullable bool), created_at`. Written best-effort at end of each `/chat/ask` stream. Migration in `_migrate_db()` is additive (try/except `CREATE TABLE`).

### Push notifications
- `PushSubscription` model + `push_subscriptions` table (endpoint, subscription JSON, platform, 3 preference booleans)
- `/m/push/subscribe`, `/m/push/unsubscribe`, `/m/push/preferences`, `/m/push/vapid-public-key` routes
- `send_notifications.py` — standalone sender, three triggers: bowling_tomorrow (6 PM prior evening), bowling_tonight (9 AM bowl day), scores_posted (after `week.is_entered`). Per-week `notif_*_sent` flags prevent duplicates.
- `com.dglc.bowling-notify` launchd timer on utilityserver, 10-min interval
- VAPID keys in `.env` (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_PEM`, `VAPID_CLAIMS_EMAIL`) — never change after first subscriber
- Me tab: iOS install prompt → permission button → preference toggles (bowling tomorrow / tonight / scores)

### Still to build
- Season rollover wizard

## Data Quality Issues

### Tietjen
Bowler id=244 has `first_name="Ma"` — truncated in the original 2007-2008 spreadsheet (XLS also shows "Ma"). Cannot determine correct name from source data; needs manual lookup.

### Missing first names (source data never included them)
Four early bowlers have no first name in any XLS file — these are unfixable from existing spreadsheets:
- id=185 Casey, id=186 Dejackmo, id=201 Parker, id=214 Wagner

### Incomplete score imports — ✅ VERIFIED CORRECT (2026-04-26)
All previously flagged cases (Zorlas 2010-2011, Gellert 2015-2016, Maute 2016-2017, Tellie 2016-2017, Brian Lewis 2016-2017) were verified against individual bowler sheets. DB matches XLS exactly — those bowlers simply bowled fewer weeks. Caution: the XLS "final handicap" tab contains the *prior* season's data, not the current year's; comparisons against it produce false positives.

### Bowler merge procedure
When merging duplicates: (1) find both Bowler rows by name, (2) re-point all FK refs (Roster.bowler_id, MatchupEntry.bowler_id, TournamentEntry.bowler_id, UserAccount.bowler_id, PushSubscription.bowler_id) to canonical record, (3) delete duplicate.

No pending merges — all resolved as of 2026-04-26:
- Ramich: Joel (id=105) and Neil (id=280) are separate legitimate bowlers, both with correct first names
- Martorana: Scott (id=97) and Mike (id=295) are separate legitimate bowlers, both with correct first names

### Historical same-surname pairs (confirmed separate bowlers, verified 2026-04-26)
These are all distinct people with separate DB records and non-overlapping or distinguishable histories. No merging was done or should be done.
- Lewis: David (id=34) and Brian (id=90, bowled 2015-2020 only)
- Faehner: Josh (id=16) and Kyle (id=17)
- Drews: Jon (id=12) and Mike (id=13)
- Ferrante: Dan (id=18) and Ryan (id=19) — previously noted Ferrante Daniel id=172 no longer exists in DB

## Git Workflow

CLAUDE.md pushes directly to main. All other code and documentation changes use feature branches + PRs. See global CLAUDE.md for full workflow.

For `gh` CLI: token is embedded in the remote URL — prefix commands with:
```bash
GITHUB_TOKEN=$(git remote get-url origin | sed 's/.*:\(.*\)@.*/\1/')
```

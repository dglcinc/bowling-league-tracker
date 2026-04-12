"""
Bowling League Tracker — Flask application entry point.
Run with: python app.py
Then open http://localhost:5000 in your browser.
"""

import time

from dotenv import load_dotenv
load_dotenv()  # loads .env from project root before Config reads os.environ

from flask import Flask, redirect, request, url_for, abort, render_template
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from models import db
from flask_mail import Mail
from extensions import login_manager, limiter

mail = Mail()

# Throttle: don't write a backup more than once per 60 seconds
_last_backup_time: float = 0.0
_BACKUP_THROTTLE_SECS = 60
_BACKUP_KEEP = 30   # number of dated backups to retain


def _do_backup(app):
    """Copy the live SQLite file to the backup directory, prune old copies."""
    global _last_backup_time
    now = time.monotonic()
    if now - _last_backup_time < _BACKUP_THROTTLE_SECS:
        return
    _last_backup_time = now

    try:
        db_path = Path(app.config['db_path'])
        backup_dir = Path(app.config['BACKUP_DIR'])
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        dest = backup_dir / f'league-{stamp}.db'
        shutil.copy2(db_path, dest)

        # Prune: keep only the N most recent backups
        backups = sorted(backup_dir.glob('league-*.db'))
        for old in backups[:-_BACKUP_KEEP]:
            old.unlink(missing_ok=True)
    except Exception:
        pass  # never let backup errors surface to the user


_VIEWER_DEFAULTS = [
    ('reports.wkly_alpha',    'Weekly Alpha',        True),
    ('reports.bowler_detail', 'Bowler Stats',        True),
    ('reports.team_points',   'Points',              True),
    ('reports.ytd_alpha',     'YTD Alpha',           True),
    ('reports.week_prizes',   'Prizes & Standings',  True),
    ('payout.payout_overview','Payout',              True),
    ('reports.print_batch',   'Print Batch',         False),
    ('records.records',       'Records',             True),
    ('records.bowler_dir',    'Bowler Directory',    True),
]


def _migrate_db(db):
    """Add new columns to existing tables without dropping data."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE seasons ADD COLUMN bowling_format VARCHAR(10) DEFAULT 'single'",
        "ALTER TABLE weeks ADD COLUMN tournament_type VARCHAR(32)",
        "CREATE TABLE IF NOT EXISTS league_settings (id INTEGER PRIMARY KEY, league_name VARCHAR(128) DEFAULT 'Mountain Lakes Men''s Bowling League', use_nickname BOOLEAN DEFAULT 0)",
        "INSERT OR IGNORE INTO league_settings (id, league_name, use_nickname) VALUES (1, 'Mountain Lakes Men''s Bowling League', 0)",
        "ALTER TABLE teams ADD COLUMN captain_name VARCHAR(64)",
        "ALTER TABLE league_settings ADD COLUMN show_captain_name BOOLEAN DEFAULT 0",
        # One-time: move existing team names into captain_name, then standardize team names
        "UPDATE teams SET captain_name = name WHERE captain_name IS NULL AND name NOT LIKE 'Team %'",
        "UPDATE teams SET name = 'Team ' || CAST(number AS TEXT) WHERE name NOT LIKE 'Team %' AND name != 'Pinheads'",
        "UPDATE teams SET name = 'Pinheads' WHERE number = 2 AND season_id IN (SELECT id FROM seasons WHERE is_active = 1)",
        "ALTER TABLE payout_configs ADD COLUMN team_award_pcts_json TEXT DEFAULT '[40, 40, 20]'",
        "ALTER TABLE payout_configs ADD COLUMN team_place_pcts_json TEXT DEFAULT '[[35,25,20,20],[35,25,20,20],[60,40]]'",
        "ALTER TABLE payout_configs ADD COLUMN championship_start_week INTEGER DEFAULT 20",
        # Auth
        "ALTER TABLE bowlers ADD COLUMN is_editor BOOLEAN DEFAULT 0",
        "UPDATE bowlers SET is_editor = 1 WHERE id = 34",
        # Rename tournament_type keys — personal names removed from DB
        "UPDATE weeks SET tournament_type = 'indiv_scratch' WHERE tournament_type = 'harry_russell'",
        "UPDATE weeks SET tournament_type = 'indiv_hcp_1'   WHERE tournament_type = 'chad_harris'",
        "UPDATE weeks SET tournament_type = 'indiv_hcp_2'   WHERE tournament_type = 'shep_belyea'",
        # Configurable tournament display names per season
        "ALTER TABLE seasons ADD COLUMN name_club_championship VARCHAR(128) DEFAULT 'Club Championship'",
        "ALTER TABLE seasons ADD COLUMN name_indiv_scratch VARCHAR(128) DEFAULT 'Harry E. Russell Championship'",
        "ALTER TABLE seasons ADD COLUMN name_indiv_hcp_1 VARCHAR(128) DEFAULT 'Chad Harris Memorial Bowl'",
        "ALTER TABLE seasons ADD COLUMN name_indiv_hcp_2 VARCHAR(128) DEFAULT 'Shep Belyea Open'",
        # Venue distinction: which bowling alley was used for each season
        "ALTER TABLE seasons ADD COLUMN venue VARCHAR(32) DEFAULT 'boonton_lanes'",
        "UPDATE seasons SET venue = 'mountain_lakes_club' WHERE name < '2024-2025'",
        # Bowling night times (configurable per season, shown on mobile home screen)
        "ALTER TABLE seasons ADD COLUMN arrival_time VARCHAR(16) DEFAULT '7:45 PM'",
        "ALTER TABLE seasons ADD COLUMN start_time VARCHAR(16) DEFAULT '8:00 PM'",
        # Optional home-page message (editor-settable, shown below last-week result)
        "ALTER TABLE seasons ADD COLUMN home_message TEXT",
        # OTP login — replaces magic links for day-to-day sign-in
        """CREATE TABLE IF NOT EXISTS login_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bowler_id INTEGER NOT NULL REFERENCES bowlers(id),
            code VARCHAR(6) NOT NULL,
            expires_at DATETIME NOT NULL,
            used_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    with db.engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # column already exists or constraint satisfied

    # Seed viewer_permissions defaults (idempotent)
    from models import ViewerPermission
    for endpoint, label, accessible in _VIEWER_DEFAULTS:
        if not ViewerPermission.query.get(endpoint):
            db.session.add(ViewerPermission(
                endpoint=endpoint,
                label=label,
                viewer_accessible=accessible,
            ))
    db.session.commit()

    # Make schedule.team1_id / team2_id nullable (SQLite requires table recreation)
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(schedule)"))
            notnull = {row[1]: row[3] for row in result.fetchall()}
            if notnull.get('team1_id', 1) != 0:  # 0 = nullable, 1 = NOT NULL
                conn.execute(text("ALTER TABLE schedule RENAME TO _schedule_old"))
                conn.execute(text("""
                    CREATE TABLE schedule (
                        id INTEGER PRIMARY KEY,
                        season_id INTEGER NOT NULL REFERENCES seasons(id),
                        week_num INTEGER NOT NULL,
                        matchup_num INTEGER NOT NULL,
                        team1_id INTEGER REFERENCES teams(id),
                        team2_id INTEGER REFERENCES teams(id),
                        lane_pair VARCHAR(8),
                        UNIQUE(season_id, week_num, matchup_num)
                    )
                """))
                conn.execute(text("INSERT INTO schedule SELECT * FROM _schedule_old"))
                conn.execute(text("DROP TABLE _schedule_old"))
                conn.commit()
    except Exception:
        pass

    # Backfill post-season tournament weeks for seasons that only have regular weeks
    from models import Season, Week
    from datetime import timedelta
    from routes.admin import _POSTSEASON_WEEKS
    seasons = Season.query.all()
    for season in seasons:
        max_wk = db.session.query(db.func.max(Week.week_num)).filter_by(season_id=season.id).scalar() or 0
        if max_wk == season.num_weeks:
            # Post-season weeks are missing — add them
            for offset, (tt, is_pos) in enumerate(_POSTSEASON_WEEKS, start=1):
                wn = season.num_weeks + offset
                last = Week.query.filter_by(season_id=season.id, week_num=wn - 1).first()
                wk = Week(
                    season_id=season.id,
                    week_num=wn,
                    tournament_type=tt,
                    is_position_night=is_pos,
                )
                if last and last.date:
                    wk.date = last.date + timedelta(weeks=1)
                db.session.add(wk)
    db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Trust proxy headers from Caddy so url_for(_external=True) uses https://
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    app.jinja_env.globals['enumerate'] = enumerate

    @login_manager.user_loader
    def load_user(user_id):
        from models import Bowler
        return db.session.get(Bowler, int(user_id))

    with app.app_context():
        db.create_all()
        _migrate_db(db)

    # Automatic DB backup after every committed write (throttled to once per minute)
    from sqlalchemy import event

    @event.listens_for(db.session, 'after_commit')
    def _after_commit(session):
        _do_backup(app)

    # Register blueprints
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.entry import entry_bp
    from routes.reports import reports_bp
    from routes.payout import payout_bp
    from routes.records import records_bp
    from routes.mobile import mobile_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(entry_bp, url_prefix='/entry')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(payout_bp, url_prefix='/payout')
    app.register_blueprint(records_bp, url_prefix='/reports')
    app.register_blueprint(mobile_bp, url_prefix='/m')

    # Mobile redirect — runs before auth check so mobile users land on /m/ by default.
    # Skipped for: static files, auth routes, mobile routes themselves, prefer_desktop cookie.
    def _is_mobile_ua():
        ua = request.user_agent.string.lower()
        return 'iphone' in ua or ('android' in ua and 'mobile' in ua)

    @app.before_request
    def mobile_redirect():
        ep = request.endpoint
        if ep is None or ep == 'static':
            return
        if ep.startswith('auth.') or ep.startswith('mobile.'):
            return
        if request.cookies.get('prefer_desktop'):
            return
        if _is_mobile_ua():
            return redirect(url_for('mobile.home'))

    # Global auth enforcement — runs before every request
    @app.before_request
    def check_auth():
        from flask import request as req
        from flask_login import current_user
        from models import ViewerPermission

        ep = req.endpoint

        # Let Flask serve static files and handle missing routes without interference
        if ep is None or ep == 'static':
            return

        # Auth routes and root index are always public or universally accessible
        if ep.startswith('auth.'):
            return

        # Mobile routes are accessible to any authenticated user
        if ep.startswith('mobile.'):
            return

        # Require login for everything else
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=req.url))

        # Editors have full access
        if current_user.is_editor:
            return

        # Root index just redirects — allow all authenticated users
        if ep == 'index':
            return

        # Viewers: check the permissions table
        perm = ViewerPermission.query.get(ep)
        if perm and perm.viewer_accessible:
            return

        abort(403)

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.context_processor
    def inject_globals():
        from models import Season, Week, LeagueSettings, WebAuthnCredential
        from flask_login import current_user
        active = Season.query.filter_by(is_active=True).first()
        current_week = 0
        if active:
            last = (Week.query
                    .filter_by(season_id=active.id, is_entered=True)
                    .order_by(Week.week_num.desc())
                    .first())
            current_week = last.week_num if last else 0
        settings = db.session.get(LeagueSettings, 1)
        has_passkey = False
        if current_user.is_authenticated:
            has_passkey = WebAuthnCredential.query.filter_by(
                bowler_id=current_user.id
            ).first() is not None
        all_seasons = Season.query.order_by(Season.name.desc()).all()
        latest_entered = {}
        for s in all_seasons:
            lw = (Week.query
                  .filter_by(season_id=s.id, is_entered=True)
                  .order_by(Week.week_num.desc())
                  .first())
            latest_entered[s.id] = lw.week_num if lw else 0
        seasons_with_data = [s for s in all_seasons if latest_entered.get(s.id, 0) > 0]

        # Determine which season the current page is about (for navbar dropdown label)
        from flask import request as _req
        view_args = _req.view_args or {}
        sid = view_args.get('season_id')
        view_season = db.session.get(Season, sid) if sid else active

        return {
            'active_season': active,
            'view_season': view_season,
            'current_week': current_week,
            'league_settings': settings,
            'has_passkey': has_passkey,
            'all_seasons': all_seasons,
            'latest_entered': latest_entered,
            'seasons_with_data': seasons_with_data,
        }

    @app.route('/')
    def index():
        from datetime import timedelta
        from flask_login import current_user
        from models import (Season, Week, ScheduleEntry, MatchupEntry,
                            TeamPoints, Roster, TournamentEntry, Team)
        from calculations import get_team_standings

        season = Season.query.filter_by(is_active=True).first()
        if not season:
            return redirect(url_for('admin.seasons'))

        # ── Up Next ──────────────────────────────────────────────────────────
        upcoming_week = (Week.query
                         .filter_by(season_id=season.id, is_entered=False,
                                    is_cancelled=False)
                         .order_by(Week.week_num)
                         .first())

        roster = None
        my_team = None
        my_matchup = None
        all_matchups = []
        games_played = 0

        if current_user.is_authenticated:
            roster = Roster.query.filter_by(
                bowler_id=current_user.id, season_id=season.id
            ).first()
            my_team = roster.team if roster else None

        if upcoming_week:
            all_matchups = (ScheduleEntry.query
                            .filter_by(season_id=season.id,
                                       week_num=upcoming_week.week_num)
                            .order_by(ScheduleEntry.matchup_num)
                            .all())
            if my_team:
                my_matchup = next(
                    (m for m in all_matchups
                     if m.team1_id == my_team.id or m.team2_id == my_team.id),
                    None,
                )

        if current_user.is_authenticated:
            regular_entries = (MatchupEntry.query
                               .filter_by(season_id=season.id,
                                          bowler_id=current_user.id,
                                          is_blind=False)
                               .filter(MatchupEntry.week_num <= season.num_weeks)
                               .all())
            for e in regular_entries:
                games_played += len(e.games_night1)

        # preview_week param lets an editor preview result display for any week
        _preview_wn = request.args.get('preview_week', type=int)
        if _preview_wn and current_user.is_authenticated and current_user.is_editor:
            last_week = Week.query.filter_by(season_id=season.id, week_num=_preview_wn).first()
        else:
            last_week = (Week.query
                         .filter_by(season_id=season.id, is_entered=True)
                         .order_by(Week.week_num.desc())
                         .first())

        # Variables populated below depending on last week's event type
        last_week_type = None          # 'regular' | 'championship' | 'solo'
        last_week_pts = None           # my team's points (regular)
        last_week_opp_pts = None       # opponent's points (regular)
        last_week_opp = None           # opponent Team object (regular)
        last_week_champ = []           # [{team, pts}, ...] sorted desc (championship)
        last_week_top3 = []            # [TournamentEntry, ...] top 3 (solo)

        _SOLO_TYPES = {'indiv_scratch', 'indiv_hcp_1', 'indiv_hcp_2'}

        if last_week:
            tt = last_week.tournament_type
            if tt == 'club_championship':
                last_week_type = 'championship'
                wk_pts = TeamPoints.query.filter_by(
                    season_id=season.id, week_num=last_week.week_num
                ).all()
                totals = {}
                for p in wk_pts:
                    totals[p.team_id] = totals.get(p.team_id, 0) + p.points_earned
                teams_in_champ = Team.query.filter(Team.id.in_(totals.keys())).all()
                last_week_champ = sorted(
                    [{'team': t, 'pts': totals[t.id]} for t in teams_in_champ],
                    key=lambda x: -x['pts']
                )
            elif tt in _SOLO_TYPES:
                last_week_type = 'solo'
                entries = TournamentEntry.query.filter_by(
                    season_id=season.id, week_num=last_week.week_num
                ).all()
                # Sort by total_with_hcp for handicap events, total_scratch for scratch
                use_hcp = tt in ('indiv_hcp_1', 'indiv_hcp_2')
                entries_with_score = [
                    (e.total_with_hcp if use_hcp else e.total_scratch, e)
                    for e in entries if e.games
                ]
                entries_with_score.sort(key=lambda x: -x[0])
                last_week_top3 = [
                    {'name': e.display_name, 'score': score}
                    for score, e in entries_with_score[:3]
                ]
            else:
                last_week_type = 'regular'
                if my_team:
                    wk_pts = TeamPoints.query.filter_by(
                        season_id=season.id, week_num=last_week.week_num
                    ).all()
                    totals = {}
                    for p in wk_pts:
                        totals[p.team_id] = totals.get(p.team_id, 0) + p.points_earned
                    last_week_pts = totals.get(my_team.id)
                    last_matchup = (ScheduleEntry.query
                                    .filter_by(season_id=season.id,
                                               week_num=last_week.week_num)
                                    .filter(db.or_(
                                        ScheduleEntry.team1_id == my_team.id,
                                        ScheduleEntry.team2_id == my_team.id,
                                    ))
                                    .first())
                    if last_matchup:
                        last_week_opp = (last_matchup.team2
                                         if last_matchup.team1_id == my_team.id
                                         else last_matchup.team1)
                        last_week_opp_pts = (totals.get(last_week_opp.id)
                                             if last_week_opp else None)

        # ── Standings ────────────────────────────────────────────────────────
        overall  = get_team_standings(season.id)
        fh_list  = get_team_standings(season.id, half=1)
        sh_list  = get_team_standings(season.id, half=2)
        fh_map   = {r['team'].id: r['points'] for r in fh_list}
        sh_map   = {r['team'].id: r['points'] for r in sh_list}
        teams = [
            {
                'team':   r['team'],
                'points': r['points'],
                'fh':     fh_map.get(r['team'].id, 0),
                'sh':     sh_map.get(r['team'].id, 0),
            }
            for r in overall
        ]

        # ── Schedule ─────────────────────────────────────────────────────────
        weeks_all    = (Week.query
                        .filter_by(season_id=season.id)
                        .order_by(Week.week_num)
                        .all())
        dated_weeks  = [w for w in weeks_all if w.date]
        schedule_rows = []
        if dated_weeks:
            date_to_week = {w.date: w for w in dated_weeks}
            cur = dated_weeks[0].date
            end = dated_weeks[-1].date
            while cur <= end:
                if cur in date_to_week:
                    schedule_rows.append(
                        {'date': cur, 'week': date_to_week[cur], 'is_break': False}
                    )
                else:
                    schedule_rows.append(
                        {'date': cur, 'week': None, 'is_break': True}
                    )
                cur += timedelta(weeks=1)
        else:
            schedule_rows = [
                {'date': None, 'week': w, 'is_break': False}
                for w in weeks_all
            ]

        # ── My Stats ─────────────────────────────────────────────────────────
        entries    = []
        avg        = None
        hg_scratch = None
        hs_scratch = None
        if current_user.is_authenticated:
            entries = (MatchupEntry.query
                       .filter_by(season_id=season.id,
                                  bowler_id=current_user.id)
                       .order_by(MatchupEntry.week_num)
                       .all())
            all_games = []
            for e in entries:
                all_games.extend(e.games_night1)
            if all_games:
                avg        = round(sum(all_games) / len(all_games), 1)
                hg_scratch = max(all_games)
            week_series = {}
            for e in entries:
                g = e.games_night1
                if len(g) == 3:
                    week_series[e.week_num] = max(
                        week_series.get(e.week_num, 0), sum(g)
                    )
            if week_series:
                hs_scratch = max(week_series.values())

        return render_template('home.html',
                               season=season,
                               upcoming_week=upcoming_week,
                               all_matchups=all_matchups,
                               my_team=my_team,
                               my_matchup=my_matchup,
                               games_played=games_played,
                               last_week=last_week,
                               last_week_type=last_week_type,
                               last_week_pts=last_week_pts,
                               last_week_opp_pts=last_week_opp_pts,
                               last_week_opp=last_week_opp,
                               last_week_champ=last_week_champ,
                               last_week_top3=last_week_top3,
                               teams=teams,
                               schedule_rows=schedule_rows,
                               roster=roster,
                               entries=entries,
                               avg=avg,
                               hg_scratch=hg_scratch,
                               hs_scratch=hs_scratch)

    return app


if __name__ == '__main__':
    app = create_app()
    print("\n  Bowling League Tracker running at http://localhost:5001\n")
    app.run(debug=True, host='0.0.0.0', port=5001)

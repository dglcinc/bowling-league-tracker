"""
Bowling League Tracker — Flask application entry point.
Run with: python app.py
Then open http://localhost:5000 in your browser.
"""

import time

from dotenv import load_dotenv
load_dotenv()  # loads .env from project root before Config reads os.environ

from flask import Flask, redirect, url_for, abort, render_template
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

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(entry_bp, url_prefix='/entry')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(payout_bp, url_prefix='/payout')
    app.register_blueprint(records_bp, url_prefix='/reports')

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
        from models import Season
        active = Season.query.filter_by(is_active=True).first()
        if active:
            from models import Week
            last_entered = (Week.query
                            .filter_by(season_id=active.id, is_entered=True)
                            .order_by(Week.week_num.desc())
                            .first())
            week_num = last_entered.week_num if last_entered else 0
            return redirect(url_for('reports.wkly_alpha',
                                    season_id=active.id,
                                    week_num=week_num))
        return redirect(url_for('admin.seasons'))

    return app


if __name__ == '__main__':
    app = create_app()
    print("\n  Bowling League Tracker running at http://localhost:5001\n")
    app.run(debug=True, host='0.0.0.0', port=5001)

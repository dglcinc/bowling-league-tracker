"""
Bowling League Tracker — Flask application entry point.
Run with: python app.py
Then open http://localhost:5000 in your browser.
"""

from dotenv import load_dotenv
load_dotenv()  # loads .env from project root before Config reads os.environ

from flask import Flask, redirect, url_for
from config import Config
from models import db
from flask_mail import Mail

mail = Mail()


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
    ]
    with db.engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # column already exists

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

    db.init_app(app)
    mail.init_app(app)

    app.jinja_env.globals['enumerate'] = enumerate

    with app.app_context():
        db.create_all()
        _migrate_db(db)

    # Register blueprints
    from routes.admin import admin_bp
    from routes.entry import entry_bp
    from routes.reports import reports_bp
    from routes.payout import payout_bp

    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(entry_bp, url_prefix='/entry')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(payout_bp, url_prefix='/payout')

    @app.context_processor
    def inject_globals():
        from models import Season, Week, LeagueSettings
        active = Season.query.filter_by(is_active=True).first()
        current_week = 0
        if active:
            last = (Week.query
                    .filter_by(season_id=active.id, is_entered=True)
                    .order_by(Week.week_num.desc())
                    .first())
            current_week = last.week_num if last else 0
        settings = LeagueSettings.query.get(1)
        return {'active_season': active, 'current_week': current_week, 'league_settings': settings}

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

"""
Bowling League Tracker — Flask application entry point.
Run with: python app.py
Then open http://localhost:5000 in your browser.
"""

from flask import Flask, redirect, url_for
from config import Config
from models import db


def _migrate_db(db):
    """Add new columns to existing tables without dropping data."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE seasons ADD COLUMN bowling_format VARCHAR(10) DEFAULT 'single'",
        "ALTER TABLE weeks ADD COLUMN tournament_type VARCHAR(32)",
    ]
    with db.engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # column already exists


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

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
        from models import Season, Week
        active = Season.query.filter_by(is_active=True).first()
        current_week = 0
        if active:
            last = (Week.query
                    .filter_by(season_id=active.id, is_entered=True)
                    .order_by(Week.week_num.desc())
                    .first())
            current_week = last.week_num if last else 0
        return {'active_season': active, 'current_week': current_week}

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
    app.run(debug=True, port=5001)

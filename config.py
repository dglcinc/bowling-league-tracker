"""
Configuration for Bowling League Tracker.
DB is stored in OneDrive for automatic backup.
"""

import os
from pathlib import Path


def get_db_path():
    """Locate OneDrive folder; fall back to local directory."""
    candidates = [
        Path.home() / "OneDrive - DGLC" / "Claude" / "bowling-league-tracker",
        Path.home() / "OneDrive" / "Claude" / "bowling-league-tracker",
        Path(__file__).parent / "data",
    ]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path / "league.db"
        except OSError:
            continue
    return Path(__file__).parent / "league.db"


def get_snapshot_dir():
    """Snapshots go next to the DB file."""
    db_path = get_db_path()
    snap_dir = db_path.parent / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    return snap_dir


def get_backup_dir():
    """DB backups go next to the DB file."""
    db_path = get_db_path()
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


class Config:
    db_path = get_db_path()
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "bowling-dev-key-change-in-prod")
    SNAPSHOT_DIR = get_snapshot_dir()
    BACKUP_DIR = get_backup_dir()

    # Outbound email via Microsoft Graph API (OAuth2 — replaces SMTP)
    GRAPH_TENANT_ID      = os.environ.get("GRAPH_TENANT_ID", "")
    GRAPH_CLIENT_ID      = os.environ.get("GRAPH_CLIENT_ID", "")
    GRAPH_CLIENT_SECRET  = os.environ.get("GRAPH_CLIENT_SECRET", "")
    GRAPH_SENDER_EMAIL   = os.environ.get("GRAPH_SENDER_EMAIL", "")

    # Outbound email via Exchange SMTP (legacy fallback — not recommended)
    MAIL_SERVER          = os.environ.get("MAIL_SERVER",  "smtp.office365.com")
    MAIL_PORT            = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS         = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME        = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD        = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER  = os.environ.get("MAIL_DEFAULT_SENDER",
                                           os.environ.get("MAIL_USERNAME", ""))

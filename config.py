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


class Config:
    db_path = get_db_path()
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "bowling-dev-key-change-in-prod")
    SNAPSHOT_DIR = get_snapshot_dir()

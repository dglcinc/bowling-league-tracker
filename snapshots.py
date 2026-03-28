"""
Auto-snapshot: after each week's scores are saved, write a JSON file
to the OneDrive snapshots directory and store a copy in the DB.
"""

import json
from datetime import datetime, date
from pathlib import Path
from calculations import get_wkly_alpha, get_team_standings, get_bowler_stats
from models import db, Snapshot, Roster, Season, Week


def _default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


def build_snapshot(season_id, week_num):
    """Build the full snapshot dict for a season/week."""
    season = Season.query.get(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first()

    alpha = get_wkly_alpha(season_id, week_num)
    standings = get_team_standings(season_id)
    standings_h1 = get_team_standings(season_id, half=1)
    standings_h2 = get_team_standings(season_id, half=2)

    bowler_rows = []
    for row in alpha:
        bowler_rows.append({
            'last_name': row['bowler'].last_name,
            'first_name': row['bowler'].first_name,
            'team': row['team'].name,
            'team_number': row['team'].number,
            'total_pins': row['total_pins'],
            'games': row['games'],
            'average': row['average'],
            'display_handicap': row['display_handicap'],
            'high_game_scratch': row['high_game_scratch'],
            'high_game_hcp': row['high_game_hcp'],
            'high_series_scratch': row['high_series_scratch'],
            'high_series_hcp': row['high_series_hcp'],
        })

    return {
        'season': season.name,
        'week_num': week_num,
        'week_date': week.date if week else None,
        'generated_at': datetime.utcnow(),
        'bowlers': bowler_rows,
        'standings': [
            {'team': s['team'].name, 'points': s['points']}
            for s in standings
        ],
        'standings_first_half': [
            {'team': s['team'].name, 'points': s['points']}
            for s in standings_h1
        ],
        'standings_second_half': [
            {'team': s['team'].name, 'points': s['points']}
            for s in standings_h2
        ],
    }


def save_snapshot(season_id, week_num, snapshot_dir):
    """Build snapshot, save to OneDrive file and DB."""
    data = build_snapshot(season_id, week_num)
    season = Season.query.get(season_id)
    json_str = json.dumps(data, default=_default, indent=2)

    # Write to OneDrive file
    filename = f"{season.name}-wk{week_num:02d}.json"
    file_path = Path(snapshot_dir) / filename
    try:
        file_path.write_text(json_str, encoding='utf-8')
    except OSError as e:
        print(f"Warning: could not write snapshot file {file_path}: {e}")

    # Upsert in DB
    existing = Snapshot.query.filter_by(
        season_id=season_id, week_num=week_num
    ).first()
    if existing:
        existing.snapshot_json = json_str
        existing.created_at = datetime.utcnow()
    else:
        snap = Snapshot(season_id=season_id, week_num=week_num, snapshot_json=json_str)
        db.session.add(snap)

    db.session.commit()
    return file_path

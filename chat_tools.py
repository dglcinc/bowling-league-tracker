"""
Read-only tool catalog the LLM can call to answer stats questions.

Each tool is a thin, read-only wrapper around helpers in `calculations.py`
and `routes/records.py`. The model never writes SQL and never sees the DB
connection — it picks a tool from `TOOL_SCHEMAS`, the server runs it via
`dispatch(name, args)`, and the JSON result is fed back to the model.
"""

from models import db, Season
from calculations import (
    get_bowler_stats,
    get_career_stats,
    build_leaders_list,
    get_weekly_prizes,
)
from routes.records import (
    _get_season_data,
    _compute_bowler_season_summaries,
    _all_time_records,
    _most_improved,
    _VENUE_LABELS,
)


# ---------- serializers ----------

def _bowler_dict(bowler):
    if bowler is None:
        return None
    return {
        'id':           bowler.id,
        'last_name':    bowler.last_name,
        'first_name':   bowler.first_name,
        'nickname':     bowler.nickname,
        'display_name': bowler.display_name,
    }


def _season_dict(season):
    if season is None:
        return None
    return {
        'id':         season.id,
        'name':       season.name,
        'start_date': season.start_date.isoformat() if season.start_date else None,
        'num_weeks':  season.num_weeks,
        'venue':      season.venue,
        'is_active':  bool(season.is_active),
    }


def _team_dict(team):
    if team is None:
        return None
    return {
        'id':        team.id,
        'season_id': team.season_id,
        'number':    team.number,
        'name':      team.name,
    }


def _filtered_summaries(venue):
    """Compute summaries for the records helpers and apply optional venue filter."""
    seasons, tournament_weeks = _get_season_data()
    summaries = _compute_bowler_season_summaries(seasons, tournament_weeks)
    if venue and venue in _VENUE_LABELS:
        filtered = [s for s in summaries
                    if (s['season'].venue or 'boonton_lanes') == venue]
        filtered_seasons = [s for s in seasons
                            if (s.venue or 'boonton_lanes') == venue]
        return filtered, filtered_seasons
    return summaries, seasons


# ---------- tool implementations ----------

def bowler_career_stats(bowler_id):
    """Per-season stats for one bowler across every season they bowled."""
    rows = get_career_stats(bowler_id)
    out = []
    for r in rows:
        out.append({
            'season':              _season_dict(r.get('season')),
            'team':                _team_dict(r.get('team')),
            'venue':               r.get('venue'),
            'has_data':            r.get('has_data'),
            'avg':                 r.get('avg'),
            'games':               r.get('games'),
            'high_game_scratch':   r.get('high_game_scratch'),
            'high_series_scratch': r.get('high_series_scratch'),
            'high_game_hcp':       r.get('high_game_hcp'),
            'high_series_hcp':     r.get('high_series_hcp'),
            'prior_hcp':           r.get('prior_hcp'),
        })
    return out


def bowler_season_stats(bowler_id, season_id, through_week=None):
    """YTD stats for a bowler in one season (excludes weekly_stats list to keep
    the payload compact — call again with `through_week` to slice if needed)."""
    s = get_bowler_stats(bowler_id, season_id, through_week=through_week)
    out = {k: v for k, v in s.items() if k != 'weekly_stats'}
    return out


def season_leaders(season_id, through_week=None, min_games=None, top10=False):
    """Bowlers in one season ranked by season average descending."""
    if through_week is None:
        season = db.session.get(Season, season_id)
        through_week = season.num_weeks if season else 26
    leaders, avg_rows = build_leaders_list(season_id, through_week,
                                           min_games=min_games, top10=top10)
    rows = avg_rows if (min_games or top10) else leaders
    return [{
        'bowler':              _bowler_dict(r['bowler']),
        'team':                _team_dict(r['team']),
        'average':             r['average'],
        'games':               r['games'],
        'handicap':            r['handicap'],
        'high_game_scratch':   r['high_game_scratch'],
        'high_game_hcp':       r['high_game_hcp'],
        'high_series_scratch': r['high_series_scratch'],
        'high_series_hcp':     r['high_series_hcp'],
    } for r in rows]


def all_time_records(venue='all', category='all', limit=20):
    """All-time per-bowler bests across all seasons. Optionally filter by venue
    ('all' | 'mountain_lakes_club' | 'boonton_lanes') and category
    ('all' | 'hg_scratch' | 'hs_scratch' | 'hg_hcp' | 'hs_hcp' | 'avg')."""
    filtered, _ = _filtered_summaries(venue if venue != 'all' else None)
    hg_s, hs_s, hg_h, hs_h, avg = _all_time_records(filtered)

    def _ser(rows, score_key, season_key, week_key):
        return [{
            'bowler': _bowler_dict(r['bowler']),
            'score':  r[score_key],
            'season': _season_dict(r[season_key]),
            'week':   r.get(week_key),
        } for r in rows[:limit] if r[score_key]]

    def _ser_avg(rows):
        return [{
            'bowler': _bowler_dict(r['bowler']),
            'avg':    r['best_avg'],
            'games':  r['best_avg_games'],
            'season': _season_dict(r['best_avg_season']),
        } for r in rows[:limit] if r['best_avg']]

    out = {
        'hg_scratch': _ser(hg_s, 'hg_scratch', 'hg_scratch_season', 'hg_scratch_week'),
        'hs_scratch': _ser(hs_s, 'hs_scratch', 'hs_scratch_season', 'hs_scratch_week'),
        'hg_hcp':     _ser(hg_h, 'hg_hcp',     'hg_hcp_season',     'hg_hcp_week'),
        'hs_hcp':     _ser(hs_h, 'hs_hcp',     'hs_hcp_season',     'hs_hcp_week'),
        'avg':        _ser_avg(avg),
    }
    if category != 'all' and category in out:
        return {category: out[category]}
    return out


def most_improved(venue='all', limit=20):
    """Largest single-season average improvement between consecutive bowled seasons."""
    filtered, _ = _filtered_summaries(venue if venue != 'all' else None)
    rows = _most_improved(filtered)[:limit]
    return [{
        'bowler':      _bowler_dict(r['bowler']),
        'from_season': _season_dict(r['from_season']),
        'to_season':   _season_dict(r['to_season']),
        'from_avg':    r['from_avg'],
        'to_avg':      r['to_avg'],
        'gain':        r['gain'],
    } for r in rows]


def query_db(sql, params=None):
    """Run a read-only SELECT against the league SQLite DB. Up to 200 rows
    are returned. Single statement only, mutation keywords rejected at
    string level, and PRAGMA query_only is set on the connection as a
    second layer of defense."""
    import re
    from sqlalchemy import text

    if not isinstance(sql, str):
        return {'error': 'sql must be a string'}
    cleaned = sql.strip().rstrip(';').strip()
    if not cleaned:
        return {'error': 'sql is empty'}
    if ';' in cleaned:
        return {'error': 'only one statement allowed; remove embedded ;'}

    tokens = [t for t in re.split(r'[\s(),;]+', cleaned.upper()) if t]
    if not tokens or tokens[0] not in ('SELECT', 'WITH'):
        return {'error': 'must start with SELECT or WITH'}

    forbidden_keywords = {
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER',
        'ATTACH', 'DETACH', 'PRAGMA', 'REPLACE', 'GRANT', 'REVOKE',
        'TRUNCATE', 'VACUUM',
    }
    bad = forbidden_keywords & set(tokens)
    if bad:
        return {'error': f'forbidden keyword(s): {", ".join(sorted(bad))}'}

    forbidden_tables = (
        'user_account', 'request_log', 'chat_log', 'push_subscription',
        'viewer_permission', 'audit_log', 'payout_config',
        'webauthn_credential', 'sqlite_master', 'sqlite_sequence',
    )
    cleaned_lower = cleaned.lower()
    for name in forbidden_tables:
        if name in cleaned_lower:
            return {'error': f'forbidden table: {name}'}

    if params is not None and not isinstance(params, dict):
        return {'error': 'params must be an object/dict'}

    try:
        with db.engine.connect() as conn:
            conn.exec_driver_sql('PRAGMA query_only = 1')
            try:
                result = conn.execute(text(cleaned), params or {})
                rows = result.mappings().all()
            finally:
                conn.exec_driver_sql('PRAGMA query_only = 0')
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}

    capped = [dict(r) for r in rows[:200]]
    return {
        'rows':      capped,
        'row_count': len(capped),
        'truncated': len(rows) > 200,
    }


def weekly_prizes(season_id, week_num):
    """Four prize-category winners (HG/HS scratch/hcp) for one week."""
    p = get_weekly_prizes(season_id, week_num)
    if not p:
        return None

    def _cat(c):
        return {
            'score':   c['score'],
            'winners': [{'bowler': _bowler_dict(w['bowler']), 'score': w['score']}
                        for w in c['winners']],
        }

    return {
        'hg_scratch': _cat(p['hg_scratch']),
        'hg_hcp':     _cat(p['hg_hcp']),
        'hs_scratch': _cat(p['hs_scratch']),
        'hs_hcp':     _cat(p['hs_hcp']),
    }


# ---------- tool schemas ----------
#
# Anthropic's tool spec: flat dicts with `name`, `description`, `input_schema`.
# Passed straight to `client.messages.stream(tools=...)`.

TOOL_SCHEMAS = [
    {
        'name': 'bowler_career_stats',
        'description': 'Per-season stats for one bowler across every season they bowled. Returns avg, games, high game/series (scratch and handicap) per season.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'bowler_id': {'type': 'integer', 'description': 'Bowler id from the bowlers table.'},
            },
            'required': ['bowler_id'],
        },
    },
    {
        'name': 'bowler_season_stats',
        'description': 'YTD stats for one bowler in one season: running average, games, current handicap, high game/series.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'bowler_id':    {'type': 'integer'},
                'season_id':    {'type': 'integer'},
                'through_week': {'type': 'integer', 'description': 'Optional — only include weeks <= this number.'},
            },
            'required': ['bowler_id', 'season_id'],
        },
    },
    {
        'name': 'season_leaders',
        'description': 'Ranked list of bowlers in one season by season average (descending).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'season_id':    {'type': 'integer'},
                'through_week': {'type': 'integer', 'description': 'Optional — defaults to season.num_weeks.'},
                'min_games':    {'type': 'integer', 'description': 'Optional — minimum games to qualify.'},
                'top10':        {'type': 'boolean', 'description': 'If true, return only the top-10 distinct averages (with ties).'},
            },
            'required': ['season_id'],
        },
    },
    {
        'name': 'all_time_records',
        'description': 'All-time per-bowler bests across every season. Pick venue and/or category to narrow the result.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'venue':    {'type': 'string', 'enum': ['all', 'mountain_lakes_club', 'boonton_lanes']},
                'category': {'type': 'string', 'enum': ['all', 'hg_scratch', 'hs_scratch', 'hg_hcp', 'hs_hcp', 'avg']},
                'limit':    {'type': 'integer', 'description': 'Top N per category (default 20).'},
            },
            'required': [],
        },
    },
    {
        'name': 'most_improved',
        'description': 'Largest single-season average improvements between consecutive bowled seasons.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'venue': {'type': 'string', 'enum': ['all', 'mountain_lakes_club', 'boonton_lanes']},
                'limit': {'type': 'integer', 'description': 'Top N (default 20).'},
            },
            'required': [],
        },
    },
    {
        'name': 'query_db',
        'description': 'Run a read-only SELECT (or WITH ... SELECT) against the league SQLite DB. Up to 200 rows returned. Use for counts, sums, mins/maxes, tournament placements, and other ad-hoc aggregations that do not require handicap math. The schema is in the system prompt. Reject any non-SELECT statement.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'sql':    {'type': 'string', 'description': 'A single SELECT or WITH...SELECT statement.'},
                'params': {'type': 'object', 'description': 'Optional named parameters bound to :name placeholders in the SQL.'},
            },
            'required': ['sql'],
        },
    },
    {
        'name': 'weekly_prizes',
        'description': 'Four prize-category winners (high game / high series, scratch and handicap) for one week of one season. Returns null if no entries.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'season_id': {'type': 'integer'},
                'week_num':  {'type': 'integer'},
            },
            'required': ['season_id', 'week_num'],
        },
    },
]


_DISPATCH = {
    'bowler_career_stats':  bowler_career_stats,
    'bowler_season_stats':  bowler_season_stats,
    'season_leaders':       season_leaders,
    'all_time_records':     all_time_records,
    'most_improved':        most_improved,
    'query_db':             query_db,
    'weekly_prizes':        weekly_prizes,
}


def dispatch(name, args):
    """Run a tool by name with the given keyword args. Raises KeyError if the
    tool name is unknown — the chat blueprint catches and reports back to the model."""
    if name not in _DISPATCH:
        raise KeyError(f"Unknown tool: {name}")
    return _DISPATCH[name](**(args or {}))

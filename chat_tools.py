"""
Read-only tool catalog the LLM can call to answer stats questions.

Each tool is a thin, read-only wrapper around helpers in `calculations.py`
and `routes/records.py`. The model never writes SQL and never sees the DB
connection — it picks a tool from `TOOL_SCHEMAS`, the server runs it via
`dispatch(name, args)`, and the JSON result is fed back to the model.
"""

from models import (
    db,
    Bowler,
    Season,
    Roster,
)
from calculations import (
    get_bowler_stats,
    get_career_stats,
    build_leaders_list,
    get_team_standings,
    get_weekly_prizes,
)
from routes.records import (
    _get_season_data,
    _compute_bowler_season_summaries,
    _all_time_records,
    _most_improved,
    _fun_stats,
    _tournament_winners_by_season,
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

def list_seasons():
    """All seasons that have at least one entered week, oldest to newest."""
    seasons, _ = _get_season_data()
    return [_season_dict(s) for s in seasons]


def list_bowlers(last_name_substring=None, season_id=None, limit=50):
    """Find bowlers by last-name substring (case-insensitive). Optionally
    restrict to a single season's roster. Returns up to `limit` matches."""
    q = Bowler.query
    if last_name_substring:
        q = q.filter(Bowler.last_name.ilike(f'%{last_name_substring}%'))
    if season_id:
        rostered_ids = {
            r.bowler_id for r in
            Roster.query.with_entities(Roster.bowler_id)
                        .filter_by(season_id=season_id).all()
        }
        bowlers = [b for b in q.order_by(Bowler.last_name, Bowler.first_name).all()
                   if b.id in rostered_ids]
    else:
        bowlers = q.order_by(Bowler.last_name, Bowler.first_name).all()
    return [_bowler_dict(b) for b in bowlers[:limit]]


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


def fun_stats(venue='all'):
    """Novelty stats: lowest avg (>=30 games), most games, most 200+ games,
    lowest individual games, tournament placement counts."""
    filtered, filtered_seasons = _filtered_summaries(venue if venue != 'all' else None)
    fs = _fun_stats(filtered, filtered_seasons)

    def _avg_row(r):
        return {'bowler': _bowler_dict(r['bowler']),
                'avg':    r['avg'],
                'games':  r['games'],
                'season': _season_dict(r['season'])}

    def _games_row(r):
        return {'bowler': _bowler_dict(r['bowler']),
                'games':  r['games'],
                'season': _season_dict(r['season'])}

    def _lowest_row(r):
        return {'bowler':   _bowler_dict(r['bowler']),
                'score':    r['score'],
                'season':   _season_dict(r['season']),
                'week_num': r['week_num']}

    def _placement_row(r):
        return {'bowler':   _bowler_dict(r['bowler']) if r['bowler'] else None,
                'is_guest': r['is_guest'],
                'name':     r['name'],
                'ones':     r['ones'],
                'twos':     r['twos'],
                'threes':   r['threes'],
                'total':    r['total']}

    return {
        'min_qualified':     fs['min_qualified'],
        'worst_avg':         [_avg_row(r) for r in fs['worst_avg']],
        'most_season_games': [_games_row(r) for r in fs['most_season_games']],
        'most_career_games': [{'bowler':  _bowler_dict(r['bowler']),
                               'total':   r['total'],
                               'seasons': r['seasons']}
                              for r in fs['most_career_games']],
        'most_200':          [{'bowler': _bowler_dict(r['bowler']),
                               'count':  r['count']} for r in fs['most_200']],
        'lowest_games':      [_lowest_row(r) for r in fs['lowest_games']],
        'tournament_placements_per_type': {
            tt: [_placement_row(r) for r in rows]
            for tt, rows in fs['tourn_per_type'].items()
        },
        'tournament_placements_overall': [_placement_row(r) for r in fs['tourn_overall']],
    }


def tournament_winners(venue='all'):
    """Top-3 individual tournament finishers and club championship results per season."""
    _, filtered_seasons = _filtered_summaries(venue if venue != 'all' else None)
    rows = _tournament_winners_by_season(filtered_seasons)

    def _entry(e):
        if e is None:
            return None
        return {
            'bowler':         _bowler_dict(e.bowler) if e.bowler_id else None,
            'guest_name':     e.guest_name,
            'place':          e.place,
            'total_scratch':  getattr(e, 'total_scratch', None),
            'total_with_hcp': getattr(e, 'total_with_hcp', None),
        }

    def _club(cr):
        return {
            'place':     cr.place,
            'team':      _team_dict(cr.team) if cr.team else None,
        }

    return [{
        'season':        _season_dict(r['season']),
        'indiv_scratch': [_entry(e) for e in r['indiv_scratch']],
        'indiv_hcp_1':   [_entry(e) for e in r['indiv_hcp_1']],
        'indiv_hcp_2':   [_entry(e) for e in r['indiv_hcp_2']],
        'club_by_place': {place: _club(cr) for place, cr in r['club_by_place'].items()},
    } for r in rows]


def team_standings(season_id, half=None, through_week=None):
    """Team points totals for one season. `half` = 1 (first half), 2 (second
    half), or None (full season). `through_week` caps the week range."""
    rows = get_team_standings(season_id, half=half, through_week=through_week)
    return [{
        'team':   _team_dict(r['team']),
        'points': r['points'],
    } for r in rows]


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


# ---------- Ollama tool schemas ----------

TOOL_SCHEMAS = [
    {
        'type': 'function',
        'function': {
            'name': 'list_seasons',
            'description': 'List all seasons that have entered scores, oldest to newest. Use to resolve a season name (e.g. "2025-2026") to a season_id.',
            'parameters': {'type': 'object', 'properties': {}, 'required': []},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_bowlers',
            'description': 'Find bowlers by last-name substring (case-insensitive). Use to resolve a bowler name to a bowler_id before calling other tools.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'last_name_substring': {
                        'type': 'string',
                        'description': 'Case-insensitive substring of the last name (e.g. "lewis").',
                    },
                    'season_id': {
                        'type': 'integer',
                        'description': 'Optional — restrict to bowlers rostered in this season.',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max results to return (default 50).',
                    },
                },
                'required': [],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'bowler_career_stats',
            'description': 'Per-season stats for one bowler across every season they bowled. Returns avg, games, high game/series (scratch and handicap) per season.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'bowler_id': {'type': 'integer', 'description': 'Bowler id from list_bowlers.'},
                },
                'required': ['bowler_id'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'bowler_season_stats',
            'description': 'YTD stats for one bowler in one season: running average, games, current handicap, high game/series.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'bowler_id':    {'type': 'integer'},
                    'season_id':    {'type': 'integer'},
                    'through_week': {'type': 'integer', 'description': 'Optional — only include weeks <= this number.'},
                },
                'required': ['bowler_id', 'season_id'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'season_leaders',
            'description': 'Ranked list of bowlers in one season by season average (descending).',
            'parameters': {
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
    },
    {
        'type': 'function',
        'function': {
            'name': 'all_time_records',
            'description': 'All-time per-bowler bests across every season. Pick venue and/or category to narrow the result.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'venue':    {'type': 'string', 'enum': ['all', 'mountain_lakes_club', 'boonton_lanes']},
                    'category': {'type': 'string', 'enum': ['all', 'hg_scratch', 'hs_scratch', 'hg_hcp', 'hs_hcp', 'avg']},
                    'limit':    {'type': 'integer', 'description': 'Top N per category (default 20).'},
                },
                'required': [],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'most_improved',
            'description': 'Largest single-season average improvements between consecutive bowled seasons.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'venue': {'type': 'string', 'enum': ['all', 'mountain_lakes_club', 'boonton_lanes']},
                    'limit': {'type': 'integer', 'description': 'Top N (default 20).'},
                },
                'required': [],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'fun_stats',
            'description': 'Novelty leaderboards: lowest season averages, most games in a season, most career games, most 200+ games, lowest individual games, tournament placement counts.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'venue': {'type': 'string', 'enum': ['all', 'mountain_lakes_club', 'boonton_lanes']},
                },
                'required': [],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'tournament_winners',
            'description': 'Top-3 finishers in each individual tournament (Harry Russell scratch, hcp 1, hcp 2) and club championship team results, per season.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'venue': {'type': 'string', 'enum': ['all', 'mountain_lakes_club', 'boonton_lanes']},
                },
                'required': [],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'team_standings',
            'description': 'Team points totals for one season. half=1 → first-half, half=2 → second-half, omitted → full season.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'season_id':    {'type': 'integer'},
                    'half':         {'type': 'integer', 'enum': [1, 2]},
                    'through_week': {'type': 'integer'},
                },
                'required': ['season_id'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'weekly_prizes',
            'description': 'Four prize-category winners (high game / high series, scratch and handicap) for one week of one season. Returns null if no entries.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'season_id': {'type': 'integer'},
                    'week_num':  {'type': 'integer'},
                },
                'required': ['season_id', 'week_num'],
            },
        },
    },
]


_DISPATCH = {
    'list_seasons':         list_seasons,
    'list_bowlers':         list_bowlers,
    'bowler_career_stats':  bowler_career_stats,
    'bowler_season_stats':  bowler_season_stats,
    'season_leaders':       season_leaders,
    'all_time_records':     all_time_records,
    'most_improved':        most_improved,
    'fun_stats':            fun_stats,
    'tournament_winners':   tournament_winners,
    'team_standings':       team_standings,
    'weekly_prizes':        weekly_prizes,
}


def dispatch(name, args):
    """Run a tool by name with the given keyword args. Raises KeyError if the
    tool name is unknown — the chat blueprint catches and reports back to the model."""
    if name not in _DISPATCH:
        raise KeyError(f"Unknown tool: {name}")
    return _DISPATCH[name](**(args or {}))

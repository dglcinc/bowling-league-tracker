"""
Records route: all-time leaderboards and season comparison table.
"""

from flask import Blueprint, render_template
from sqlalchemy import func
from models import (db, Season, Week, Roster, Bowler, Team,
                    MatchupEntry, TeamPoints, TournamentEntry)
from calculations import get_bowler_stats, get_team_standings

records_bp = Blueprint('records', __name__)


def _get_season_data():
    """
    Return all seasons that have at least one entered week, sorted by name.
    Also returns the set of regular-week (non-tournament) week nums per season.
    """
    entered_season_ids = (
        db.session.query(Week.season_id)
        .filter(Week.is_entered == True)
        .distinct()
        .subquery()
    )
    seasons = (Season.query
               .filter(Season.id.in_(entered_season_ids))
               .order_by(Season.name)
               .all())

    # tournament week nums per season_id
    tournament_weeks = {}
    for s in seasons:
        tournament_weeks[s.id] = {
            w.week_num for w in
            Week.query.filter_by(season_id=s.id)
            .filter(Week.tournament_type.isnot(None)).all()
        }
    return seasons, tournament_weeks


def _compute_bowler_season_summaries(seasons, tournament_weeks):
    """
    For each (bowler, season) that has regular-week entries, compute
    {avg, games, high_game_scratch, high_series_scratch}.
    Returns list of dicts, each with bowler, season, and stats.
    """
    summaries = []
    for season in seasons:
        twks = tournament_weeks[season.id]
        # Distinct bowlers with entries this season
        bowler_ids = (
            db.session.query(MatchupEntry.bowler_id)
            .filter_by(season_id=season.id, is_blind=False)
            .filter(MatchupEntry.week_num.notin_(twks) if twks else True)
            .distinct()
            .all()
        )
        for (bid,) in bowler_ids:
            stats = get_bowler_stats(bid, season.id)
            if stats['cumulative_games'] < 6:
                continue
            bowler = db.session.get(Bowler, bid)
            summaries.append({
                'bowler':              bowler,
                'season':              season,
                'avg':                 stats['running_avg'],
                'games':               stats['cumulative_games'],
                'high_game_scratch':   stats['ytd_high_game_scratch'],
                'high_series_scratch': stats['ytd_high_series_scratch'],
            })
    return summaries


def _all_time_records(summaries):
    """Compute all-time leaderboards from bowler-season summaries."""
    # Per-bowler bests across all seasons
    bowler_best_game   = {}  # bowler_id -> {'bowler', 'score', 'season'}
    bowler_best_series = {}
    bowler_best_avg    = {}

    for row in summaries:
        bid = row['bowler'].id

        if row['high_game_scratch'] > bowler_best_game.get(bid, {}).get('score', 0):
            bowler_best_game[bid] = {
                'bowler': row['bowler'],
                'score':  row['high_game_scratch'],
                'season': row['season'],
            }
        if row['high_series_scratch'] > bowler_best_series.get(bid, {}).get('score', 0):
            bowler_best_series[bid] = {
                'bowler': row['bowler'],
                'score':  row['high_series_scratch'],
                'season': row['season'],
            }
        if row['avg'] > bowler_best_avg.get(bid, {}).get('avg', 0):
            bowler_best_avg[bid] = {
                'bowler': row['bowler'],
                'avg':    row['avg'],
                'games':  row['games'],
                'season': row['season'],
            }

    all_time_hg  = sorted(bowler_best_game.values(),   key=lambda x: -x['score'])[:20]
    all_time_hs  = sorted(bowler_best_series.values(),  key=lambda x: -x['score'])[:20]
    all_time_avg = sorted(bowler_best_avg.values(),     key=lambda x: -x['avg'])[:20]
    return all_time_hg, all_time_hs, all_time_avg


def _iron_man(seasons):
    """Count distinct seasons each bowler has bowled in (≥ 6 regular-week games)."""
    # Use summaries computed above — but we need min_games check already done there
    # So just count how many times each bowler appears across all seasons
    # We'll re-derive from Roster joined with entry existence
    counts = {}  # bowler_id -> {seasons_count, bowler}
    for season in seasons:
        twks = {
            w.week_num for w in
            Week.query.filter_by(season_id=season.id)
            .filter(Week.tournament_type.isnot(None)).all()
        }
        bowler_ids = (
            db.session.query(MatchupEntry.bowler_id,
                             func.count(MatchupEntry.id).label('cnt'))
            .filter_by(season_id=season.id, is_blind=False)
            .filter(MatchupEntry.week_num.notin_(twks) if twks else True)
            .group_by(MatchupEntry.bowler_id)
            .having(func.count(MatchupEntry.id) >= 6)
            .all()
        )
        for (bid, _) in bowler_ids:
            if bid not in counts:
                counts[bid] = {'bowler': db.session.get(Bowler, bid), 'seasons': 0}
            counts[bid]['seasons'] += 1

    return sorted(counts.values(), key=lambda x: (-x['seasons'], x['bowler'].last_name))


def _most_improved(summaries):
    """
    Biggest single-season average improvement vs prior season.
    Only bowlers who have entries in 2+ seasons.
    """
    # Group by bowler, sort by season name (chronological since names are YYYY-YYYY)
    from collections import defaultdict
    by_bowler = defaultdict(list)
    for row in summaries:
        by_bowler[row['bowler'].id].append(row)

    improvements = []
    for bid, rows in by_bowler.items():
        rows_sorted = sorted(rows, key=lambda r: r['season'].name)
        for i in range(1, len(rows_sorted)):
            prev = rows_sorted[i - 1]
            curr = rows_sorted[i]
            gain = curr['avg'] - prev['avg']
            improvements.append({
                'bowler':       curr['bowler'],
                'from_season':  prev['season'],
                'to_season':    curr['season'],
                'from_avg':     prev['avg'],
                'to_avg':       curr['avg'],
                'gain':         gain,
            })

    improvements.sort(key=lambda x: -x['gain'])
    return improvements[:20]


def _season_comparison(seasons, summaries):
    """
    One row per season: league avg, best game, best series, team champion.
    """
    from collections import defaultdict

    # Index summaries by season
    by_season = defaultdict(list)
    for row in summaries:
        by_season[row['season'].id].append(row)

    rows = []
    for season in seasons:
        season_rows = by_season[season.id]
        if not season_rows:
            continue

        total_pins  = sum(r['avg'] * r['games'] for r in season_rows)
        total_games = sum(r['games'] for r in season_rows)
        league_avg  = round(total_pins / total_games) if total_games else 0

        best_game_row   = max(season_rows, key=lambda r: r['high_game_scratch'])
        best_series_row = max(season_rows, key=lambda r: r['high_series_scratch'])

        # Team champion: 1st place in full-season standings
        standings = get_team_standings(season.id)
        champion_team = standings[0]['team'] if standings else None

        rows.append({
            'season':            season,
            'league_avg':        league_avg,
            'high_game':         best_game_row['high_game_scratch'],
            'high_game_bowler':  best_game_row['bowler'],
            'high_series':       best_series_row['high_series_scratch'],
            'high_series_bowler': best_series_row['bowler'],
            'bowler_count':      len(season_rows),
            'champion_team':     champion_team,
        })
    return rows


@records_bp.route('/records')
def records():
    seasons, tournament_weeks = _get_season_data()
    if not seasons:
        return render_template('reports/records.html',
                               seasons=[], all_time_hg=[], all_time_hs=[],
                               all_time_avg=[], iron_man=[], most_improved=[],
                               season_comparison=[])

    summaries = _compute_bowler_season_summaries(seasons, tournament_weeks)

    all_time_hg, all_time_hs, all_time_avg = _all_time_records(summaries)
    iron_man_list    = _iron_man(seasons)
    most_improved    = _most_improved(summaries)
    season_comp      = _season_comparison(seasons, summaries)

    # Top season averages (all bowler-season combos, not just best per bowler)
    top_season_avgs  = sorted(summaries, key=lambda r: -r['avg'])[:25]

    return render_template('reports/records.html',
                           seasons=seasons,
                           all_time_hg=all_time_hg,
                           all_time_hs=all_time_hs,
                           all_time_avg=all_time_avg,
                           top_season_avgs=top_season_avgs,
                           iron_man=iron_man_list,
                           most_improved=most_improved,
                           season_comparison=season_comp)

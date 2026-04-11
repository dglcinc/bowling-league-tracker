"""
Records route: all-time leaderboards and season comparison table.
"""

from collections import defaultdict
from flask import Blueprint, render_template, request
from models import (db, Season, Week, Bowler, MatchupEntry, TournamentEntry, TeamPoints)
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
    For each (bowler, season) that has regular-week entries (min 6 games),
    compute scratch and handicap stats.
    Returns list of dicts with bowler, season, avg, games, high game/series S+H.
    """
    summaries = []
    for season in seasons:
        twks = tournament_weeks[season.id]
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
                'high_game_hcp':       stats['ytd_high_game_hcp'],
                'high_series_hcp':     stats['ytd_high_series_hcp'],
            })
    return summaries


def _all_time_records(summaries):
    """Compute per-bowler all-time bests (scratch and handicap) from summaries."""
    bowler_best = {}   # bowler_id -> best scores across all seasons

    for row in summaries:
        bid = row['bowler'].id
        if bid not in bowler_best:
            bowler_best[bid] = {
                'bowler': row['bowler'],
                'hg_scratch': 0, 'hg_scratch_season': None,
                'hs_scratch': 0, 'hs_scratch_season': None,
                'hg_hcp':     0, 'hg_hcp_season':     None,
                'hs_hcp':     0, 'hs_hcp_season':     None,
                'best_avg':   0, 'best_avg_season':   None,
                'best_avg_games': 0,
            }
        b = bowler_best[bid]
        if row['high_game_scratch'] > b['hg_scratch']:
            b['hg_scratch'] = row['high_game_scratch']
            b['hg_scratch_season'] = row['season']
        if row['high_series_scratch'] > b['hs_scratch']:
            b['hs_scratch'] = row['high_series_scratch']
            b['hs_scratch_season'] = row['season']
        if row['high_game_hcp'] > b['hg_hcp']:
            b['hg_hcp'] = row['high_game_hcp']
            b['hg_hcp_season'] = row['season']
        if row['high_series_hcp'] > b['hs_hcp']:
            b['hs_hcp'] = row['high_series_hcp']
            b['hs_hcp_season'] = row['season']
        if row['avg'] > b['best_avg']:
            b['best_avg'] = row['avg']
            b['best_avg_season'] = row['season']
            b['best_avg_games'] = row['games']

    bests = list(bowler_best.values())

    all_time_hg_s  = sorted(bests, key=lambda x: -x['hg_scratch'])[:20]
    all_time_hs_s  = sorted(bests, key=lambda x: -x['hs_scratch'])[:20]
    all_time_hg_h  = sorted(bests, key=lambda x: -x['hg_hcp'])[:20]
    all_time_hs_h  = sorted(bests, key=lambda x: -x['hs_hcp'])[:20]
    all_time_avg   = sorted(bests, key=lambda x: -x['best_avg'])[:20]
    return all_time_hg_s, all_time_hs_s, all_time_hg_h, all_time_hs_h, all_time_avg


def _most_improved(summaries):
    """Largest single-season average improvement between consecutive bowled seasons."""
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
                'bowler':      curr['bowler'],
                'from_season': prev['season'],
                'to_season':   curr['season'],
                'from_avg':    prev['avg'],
                'to_avg':      curr['avg'],
                'gain':        gain,
            })

    improvements.sort(key=lambda x: -x['gain'])
    return improvements[:20]


def _season_comparison(seasons, summaries):
    """One row per season: league avg, high game/series S+H, team champion."""
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

        best_hg_s = max(season_rows, key=lambda r: r['high_game_scratch'])
        best_hs_s = max(season_rows, key=lambda r: r['high_series_scratch'])
        best_hg_h = max(season_rows, key=lambda r: r['high_game_hcp'])
        best_hs_h = max(season_rows, key=lambda r: r['high_series_hcp'])

        standings = get_team_standings(season.id)
        champion_team = standings[0]['team'] if standings else None

        rows.append({
            'season':            season,
            'league_avg':        league_avg,
            'bowler_count':      len(season_rows),
            'hg_scratch':        best_hg_s['high_game_scratch'],
            'hg_scratch_bowler': best_hg_s['bowler'],
            'hs_scratch':        best_hs_s['high_series_scratch'],
            'hs_scratch_bowler': best_hs_s['bowler'],
            'hg_hcp':            best_hg_h['high_game_hcp'],
            'hg_hcp_bowler':     best_hg_h['bowler'],
            'hs_hcp':            best_hs_h['high_series_hcp'],
            'hs_hcp_bowler':     best_hs_h['bowler'],
            'champion_team':     champion_team,
        })
    return rows


def _tournament_winners_by_season(seasons):
    """
    For each season, return the top-3 placement for each individual tournament
    (indiv_scratch, indiv_hcp_1, indiv_hcp_2) plus the club_championship team winner.
    Returns list of dicts, one per season with data.
    """
    from calculations import get_team_standings

    # Map tournament_type → week_num per season
    rows = []
    for season in seasons:
        # Individual tournament top-3 (from TournamentEntry, sorted by total desc)
        indiv = {}
        for tt in ('indiv_scratch', 'indiv_hcp_1', 'indiv_hcp_2'):
            wk = Week.query.filter_by(season_id=season.id, tournament_type=tt).first()
            if not wk:
                indiv[tt] = []
                continue
            entries = (TournamentEntry.query
                       .filter_by(season_id=season.id, week_num=wk.week_num)
                       .all())
            if not entries:
                indiv[tt] = []
                continue
            # Sort by total_with_hcp desc for hcp events, scratch for indiv_scratch
            if tt == 'indiv_scratch':
                entries.sort(key=lambda e: -(e.total_scratch))
            else:
                entries.sort(key=lambda e: -(e.total_with_hcp))
            indiv[tt] = entries[:3]

        # Club championship: highest-points team in the club_champ week (team standings)
        champion_team = None
        standings = get_team_standings(season.id)
        if standings:
            champion_team = standings[0]['team']

        if any(indiv[tt] for tt in indiv) or champion_team:
            rows.append({
                'season':         season,
                'indiv_scratch':  indiv['indiv_scratch'],
                'indiv_hcp_1':    indiv['indiv_hcp_1'],
                'indiv_hcp_2':    indiv['indiv_hcp_2'],
                'champion_team':  champion_team,
            })
    return rows


_VENUE_LABELS = {
    'mountain_lakes_club': 'Mountain Lakes Club',
    'boonton_lanes':       'Boonton Lanes',
}


@records_bp.route('/records')
def records():
    seasons, tournament_weeks = _get_season_data()
    venue_filter = request.args.get('venue', 'all')

    if not seasons:
        return render_template('reports/records.html',
                               seasons=[],
                               venue_filter=venue_filter,
                               venue_labels=_VENUE_LABELS,
                               all_time_hg_s=[], all_time_hs_s=[],
                               all_time_hg_h=[], all_time_hs_h=[],
                               all_time_avg=[], top_season_avgs=[],
                               most_improved=[], season_comparison=[],
                               tournament_winners=[], tournament_labels={})

    summaries = _compute_bowler_season_summaries(seasons, tournament_weeks)

    # Venue filter — applied before leaderboard computation so rankings are per-venue
    if venue_filter in _VENUE_LABELS:
        filtered = [s for s in summaries
                    if (s['season'].venue or 'boonton_lanes') == venue_filter]
        filtered_seasons = [s for s in seasons
                            if (s.venue or 'boonton_lanes') == venue_filter]
    else:
        filtered = summaries
        filtered_seasons = seasons

    all_time_hg_s, all_time_hs_s, all_time_hg_h, all_time_hs_h, all_time_avg = (
        _all_time_records(filtered)
    )
    most_improved = _most_improved(filtered)
    season_comp   = _season_comparison(filtered_seasons, filtered)
    top_season_avgs = sorted(filtered, key=lambda r: -r['avg'])[:25]
    tournament_winners = _tournament_winners_by_season(filtered_seasons)

    # Tournament display names: use the active season's labels, fall back to most recent
    active = Season.query.filter_by(is_active=True).first()
    tournament_labels = (active or seasons[-1]).tournament_labels if seasons else {}

    return render_template('reports/records.html',
                           seasons=seasons,
                           venue_filter=venue_filter,
                           venue_labels=_VENUE_LABELS,
                           all_time_hg_s=all_time_hg_s,
                           all_time_hs_s=all_time_hs_s,
                           all_time_hg_h=all_time_hg_h,
                           all_time_hs_h=all_time_hs_h,
                           all_time_avg=all_time_avg,
                           top_season_avgs=top_season_avgs,
                           most_improved=most_improved,
                           season_comparison=season_comp,
                           tournament_winners=tournament_winners,
                           tournament_labels=tournament_labels)


@records_bp.route('/bowler_dir')
def bowler_dir():
    from calculations import get_career_stats
    bowlers = Bowler.query.order_by(Bowler.last_name, Bowler.first_name).all()
    dir_entries = []
    for bowler in bowlers:
        career = get_career_stats(bowler.id)
        if not career:
            continue
        best_avg = max(r['avg'] for r in career)
        best_hg  = max(r['high_game_scratch'] for r in career)
        dir_entries.append({
            'bowler':    bowler,
            'career':    career,
            'best_avg':  best_avg,
            'best_hg':   best_hg,
        })
    return render_template('reports/bowler_dir.html', dir_entries=dir_entries)

"""
Records route: all-time leaderboards and season comparison table.
"""

from collections import defaultdict
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from models import (db, Season, Week, Bowler, MatchupEntry, TournamentEntry, TeamPoints, Roster, Team, ClubChampionshipResult)
from calculations import get_bowler_stats, get_team_standings
from extensions import cache

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
    Returns list of dicts with bowler, season, team, avg, games, high game/series S+H.
    """
    # Pre-load rosters and teams to avoid per-bowler queries
    season_ids = [s.id for s in seasons]
    all_rosters = Roster.query.filter(Roster.season_id.in_(season_ids)).all()
    roster_map = {(r.bowler_id, r.season_id): r for r in all_rosters}
    team_map = {t.id: t for t in Team.query.all()}

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
            roster_row = roster_map.get((bid, season.id))
            team = team_map.get(roster_row.team_id) if roster_row else None
            summaries.append({
                'bowler':              bowler,
                'season':              season,
                'team':                team,
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

    all_time_hg_s  = sorted(bests, key=lambda x: -x['hg_scratch'])
    all_time_hs_s  = sorted(bests, key=lambda x: -x['hs_scratch'])
    all_time_hg_h  = sorted(bests, key=lambda x: -x['hg_hcp'])
    all_time_hs_h  = sorted(bests, key=lambda x: -x['hs_hcp'])
    all_time_avg   = sorted(bests, key=lambda x: -x['best_avg'])
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

        # Prefer the recorded club championship winner; fall back to season points leader
        ccr = ClubChampionshipResult.query.filter_by(
            season_id=season.id, place=1
        ).first()
        if ccr:
            champion_team = ccr.team
        else:
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
    (indiv_scratch, indiv_hcp_1, indiv_hcp_2) plus club championship team results.
    Returns list of dicts, one per season with data.
    """
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
            # Sort: (place, -score) — explicit place for historical entries that
            # have no game scores; score tiebreaks when place is absent.
            if tt == 'indiv_scratch':
                entries.sort(key=lambda e: (e.place or 99, -(e.total_scratch)))
            else:
                entries.sort(key=lambda e: (e.place or 99, -(e.total_with_hcp)))
            indiv[tt] = entries[:3]

        # Club championship: from manually entered ClubChampionshipResult rows
        club_results = (ClubChampionshipResult.query
                        .filter_by(season_id=season.id)
                        .order_by(ClubChampionshipResult.place)
                        .all())
        club_by_place = {r.place: r for r in club_results}

        if any(indiv[tt] for tt in indiv) or club_by_place:
            rows.append({
                'season':        season,
                'indiv_scratch': indiv['indiv_scratch'],
                'indiv_hcp_1':   indiv['indiv_hcp_1'],
                'indiv_hcp_2':   indiv['indiv_hcp_2'],
                'club_by_place': club_by_place,  # {1: result, 2: result, ...}
            })
    return rows


def _fun_stats(summaries):
    """Novelty stats not covered by the standard leaderboards."""
    min_qualified = 30

    # Worst season average (min 30 games)
    qualified = [r for r in summaries if r['games'] >= min_qualified]
    worst_avg = sorted(qualified, key=lambda r: r['avg'])[:20]

    # Most games bowled in a single season
    most_season_games = sorted(summaries, key=lambda r: -r['games'])[:20]

    # Most career games across all seasons
    career = defaultdict(lambda: {'bowler': None, 'total': 0, 'seasons': 0})
    for r in summaries:
        bid = r['bowler'].id
        career[bid]['bowler'] = r['bowler']
        career[bid]['total'] += r['games']
        career[bid]['seasons'] += 1
    most_career_games = sorted(career.values(), key=lambda x: -x['total'])[:20]

    # Most 200+ scratch games (career) — query individual game columns
    counts = defaultdict(int)
    for row in db.session.query(
        MatchupEntry.bowler_id,
        MatchupEntry.game1, MatchupEntry.game2, MatchupEntry.game3,
    ).filter(MatchupEntry.is_blind == False).all():
        bid = row[0]
        for g in row[1:]:
            if g and g >= 200:
                counts[bid] += 1
    most_200 = []
    for bid, cnt in counts.items():
        bowler = db.session.get(Bowler, bid)
        if bowler:
            most_200.append({'bowler': bowler, 'count': cnt})
    most_200.sort(key=lambda x: -x['count'])
    most_200 = most_200[:20]

    return {
        'worst_avg':         worst_avg,
        'most_season_games': most_season_games,
        'most_career_games': most_career_games,
        'most_200':          most_200,
        'min_qualified':     min_qualified,
    }


_BUILDER_METRICS = {
    'avg':        ('avg',                'Season Average'),
    'games':      ('games',              'Games Bowled'),
    'hg_scratch': ('high_game_scratch',  'High Game (Scratch)'),
    'hg_hcp':     ('high_game_hcp',      'High Game (Hcp)'),
    'hs_scratch': ('high_series_scratch','High Series (Scratch)'),
    'hs_hcp':     ('high_series_hcp',    'High Series (Hcp)'),
}


def _stat_builder(summaries, all_seasons, metric_key, season_id, team_name,
                  min_games, sort_asc):
    """Filter summaries and return a ranked list for the stat builder."""
    rows = summaries

    if season_id:
        rows = [r for r in rows if r['season'].id == season_id]
    if team_name:
        rows = [r for r in rows if r['team'] and r['team'].name == team_name]
    if min_games:
        rows = [r for r in rows if r['games'] >= min_games]

    field, label = _BUILDER_METRICS.get(metric_key, ('avg', 'Season Average'))
    rows = sorted(rows, key=lambda r: r[field], reverse=not sort_asc)[:50]
    return rows, label


_VENUE_LABELS = {
    'mountain_lakes_club': 'Mountain Lakes Club',
    'boonton_lanes':       'Boonton Lanes',
}


@records_bp.route('/records')
@cache.cached(timeout=600, query_string=True)
def records():
    seasons, tournament_weeks = _get_season_data()
    venue_filter = request.args.get('venue', 'all')

    # All-Time tab filter
    at_filter = request.args.get('at', 'top')
    if at_filter not in ('top', 'bottom', 'all'):
        at_filter = 'top'

    # Stat builder params
    builder_metric   = request.args.get('bm', 'avg')
    builder_season   = request.args.get('bs', '')
    builder_team     = request.args.get('bt', '')
    builder_mingames = int(request.args.get('bmg', 0) or 0)
    builder_asc      = request.args.get('basc', '') == '1'
    builder_season_id = int(builder_season) if builder_season.isdigit() else None

    empty_ctx = dict(
        seasons=[], venue_filter=venue_filter, venue_labels=_VENUE_LABELS,
        at_filter=at_filter,
        all_time_hg_s=[], all_time_hs_s=[], all_time_hg_h=[], all_time_hs_h=[],
        all_time_avg=[], top_season_avgs=[], most_improved=[], season_comparison=[],
        tournament_winners=[], tournament_labels={},
        fun_stats={}, builder_results=[], builder_label='',
        builder_metric=builder_metric, builder_season=builder_season,
        builder_team=builder_team, builder_mingames=builder_mingames,
        builder_asc=builder_asc, all_team_names=[],
    )
    if not seasons:
        return render_template('reports/records.html', **empty_ctx)

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

    def _apply_at_filter(lst):
        if at_filter == 'bottom':
            return list(reversed(lst[-20:]))
        if at_filter == 'top':
            return lst[:20]
        return lst  # 'all'

    all_time_hg_s = _apply_at_filter(all_time_hg_s)
    all_time_hs_s = _apply_at_filter(all_time_hs_s)
    all_time_hg_h = _apply_at_filter(all_time_hg_h)
    all_time_hs_h = _apply_at_filter(all_time_hs_h)
    all_time_avg  = _apply_at_filter(all_time_avg)
    most_improved = _most_improved(filtered)
    season_comp   = _season_comparison(filtered_seasons, filtered)
    top_season_avgs = sorted(filtered, key=lambda r: -r['avg'])[:25]
    tournament_winners = _tournament_winners_by_season(filtered_seasons)

    # Tournament display names: use the active season's labels, fall back to most recent
    active = Season.query.filter_by(is_active=True).first()
    tournament_labels = (active or seasons[-1]).tournament_labels if seasons else {}

    fun = _fun_stats(filtered)

    # All distinct team names for the builder team filter
    all_team_names = sorted({r['team'].name for r in summaries if r['team']})

    # Stat builder results — only compute when builder params are present
    builder_results, builder_label = [], ''
    if request.args.get('bm'):
        builder_results, builder_label = _stat_builder(
            filtered, filtered_seasons,
            builder_metric, builder_season_id, builder_team,
            builder_mingames, builder_asc,
        )

    return render_template('reports/records.html',
                           seasons=seasons,
                           venue_filter=venue_filter,
                           venue_labels=_VENUE_LABELS,
                           at_filter=at_filter,
                           all_time_hg_s=all_time_hg_s,
                           all_time_hs_s=all_time_hs_s,
                           all_time_hg_h=all_time_hg_h,
                           all_time_hs_h=all_time_hs_h,
                           all_time_avg=all_time_avg,
                           top_season_avgs=top_season_avgs,
                           most_improved=most_improved,
                           season_comparison=season_comp,
                           tournament_winners=tournament_winners,
                           tournament_labels=tournament_labels,
                           fun_stats=fun,
                           builder_results=builder_results,
                           builder_label=builder_label,
                           builder_metric=builder_metric,
                           builder_season=builder_season,
                           builder_team=builder_team,
                           builder_mingames=builder_mingames,
                           builder_asc=builder_asc,
                           all_team_names=all_team_names)


@records_bp.route('/stats/suggest', methods=['POST'])
@login_required
def suggest_stat():
    """Log a bowler's stat suggestion to a file for admin review."""
    import os, datetime
    suggestion = request.form.get('suggestion', '').strip()
    if suggestion:
        log_path = os.path.expanduser('~/bowling-data/stat_suggestions.txt')
        name = ''
        if current_user.is_authenticated:
            name = f'{current_user.first_name} {current_user.last_name}'.strip()
        with open(log_path, 'a') as f:
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            f.write(f'[{ts}] {name}: {suggestion}\n')
    flash('Thanks! Your stat idea has been logged.', 'success')
    return redirect(url_for('records.records') + '#tab-builder')


@records_bp.route('/bowler_dir')
@cache.cached(timeout=600, query_string=True)
def bowler_dir():
    from calculations import get_career_stats
    team_filter = request.args.get('team', '')

    # All distinct team names across all seasons (for filter buttons)
    all_teams = (db.session.query(Team.name)
                 .distinct()
                 .order_by(Team.name)
                 .all())
    all_team_names = [t.name for t in all_teams]

    # When a team filter is active, limit to bowlers who ever played for that team
    if team_filter:
        filtered_ids = (
            db.session.query(Roster.bowler_id)
            .join(Team, Roster.team_id == Team.id)
            .filter(Team.name == team_filter)
            .distinct()
            .all()
        )
        allowed_ids = {r.bowler_id for r in filtered_ids}
    else:
        allowed_ids = None

    bowlers = Bowler.query.order_by(Bowler.last_name, Bowler.first_name).all()
    dir_entries = []
    rostered_ids = {r.bowler_id for r in Roster.query.with_entities(Roster.bowler_id).all()}

    for bowler in bowlers:
        if bowler.id not in rostered_ids:
            continue
        if allowed_ids is not None and bowler.id not in allowed_ids:
            continue
        career = get_career_stats(bowler.id)
        scored = [r for r in career if r['has_data']]
        best_avg = max(r['avg'] for r in scored) if scored else None
        best_hg  = max(r['high_game_scratch'] for r in scored) if scored else None
        dir_entries.append({
            'bowler':    bowler,
            'career':    career,
            'best_avg':  best_avg,
            'best_hg':   best_hg,
        })
    return render_template('reports/bowler_dir.html',
                           dir_entries=dir_entries,
                           team_filter=team_filter,
                           all_team_names=all_team_names)

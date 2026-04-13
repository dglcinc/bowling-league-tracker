"""
Report routes: Wkly Alpha (printable), standings, bowler detail, high games.
"""

from flask import Blueprint, render_template, request, redirect, url_for
from models import Season, Week, Roster, Bowler, Team, MatchupEntry, TeamPoints, TournamentEntry, PayoutConfig
from calculations import (get_wkly_alpha, get_team_standings, get_bowler_stats,
                           get_iron_man_status, get_most_improved, get_weekly_prizes,
                           calculate_handicap, get_weekly_team_points, get_matchup_breakdown,
                           get_career_stats)

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/season/<int:season_id>/alpha/<int:week_num>')
def wkly_alpha(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first()
    rows = get_wkly_alpha(season_id, week_num)
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.number).all()
    team_filter = request.args.get('team', '')
    if team_filter:
        rows = [r for r in rows if r.get('team') and r['team'].name == team_filter]
    return render_template('reports/wkly_alpha.html',
                           season=season, week=week, week_num=week_num,
                           rows=rows, weeks=weeks, teams=teams,
                           team_filter=team_filter)



_PLACEHOLDER_VALUES = {100, 200, 300}


def _is_placeholder(te):
    """True for entries with only placeholder scores (game1=100/200/300, all others None or 0)."""
    if te.game1 not in _PLACEHOLDER_VALUES:
        return False
    return not any([te.game2, te.game3, te.game4, te.game5])


@reports_bp.route('/season/<int:season_id>/bowler/<int:bowler_id>')
def bowler_detail(season_id, bowler_id):
    season = Season.query.get_or_404(season_id)
    bowler = Bowler.query.get_or_404(bowler_id)
    stats = get_bowler_stats(bowler_id, season_id)
    roster = Roster.query.filter_by(bowler_id=bowler_id, season_id=season_id).first()
    career = get_career_stats(bowler_id)

    # Tournament placements: all entries for this bowler, any season, 1st/2nd/3rd
    raw_entries = TournamentEntry.query.filter_by(bowler_id=bowler_id).all()
    tournament_placements = []
    for te in raw_entries:
        wk = Week.query.filter_by(season_id=te.season_id, week_num=te.week_num).first()
        if not wk or not wk.tournament_type or wk.tournament_type == 'club_championship':
            continue
        place = te.place
        if place is None:
            # Compute rank from actual scores
            all_te = TournamentEntry.query.filter_by(
                season_id=te.season_id, week_num=te.week_num).all()
            if wk.tournament_type == 'indiv_scratch':
                ranked = sorted(all_te, key=lambda e: -e.total_scratch)
            else:
                ranked = sorted(all_te, key=lambda e: -e.total_with_hcp)
            for i, r in enumerate(ranked, 1):
                if r.id == te.id:
                    place = i
                    break
        if not place or place > 3:
            continue
        s = Season.query.get(te.season_id)
        is_ph = _is_placeholder(te)
        if wk.tournament_type == 'indiv_scratch':
            raw_score = te.total_scratch
        else:
            raw_score = te.total_with_hcp
        score = raw_score if (not is_ph and raw_score > 0) else None
        tournament_placements.append({
            'season':           s,
            'tournament_type':  wk.tournament_type,
            'place':            place,
            'score':            score,
        })
    tournament_placements.sort(key=lambda x: x['season'].name)

    return render_template('reports/bowler_detail.html',
                           season=season, bowler=bowler,
                           stats=stats, roster=roster,
                           career=career,
                           tournament_placements=tournament_placements)


def _build_high_games_leaders(season_id, through_week, min_games=0):
    """Shared helper: build sorted leader lists for high games report."""
    roster_entries = (Roster.query
                      .filter_by(season_id=season_id, active=True)
                      .join(Bowler)
                      .order_by(Bowler.last_name)
                      .all())
    leaders = []
    for r in roster_entries:
        stats = get_bowler_stats(r.bowler_id, season_id, through_week)
        g = stats['cumulative_games']
        if g == 0 or g < min_games:
            continue
        leaders.append({
            'bowler': r.bowler,
            'team': r.team,
            'average': stats['running_avg'],
            'handicap': stats['display_handicap'],
            'high_game_scratch': stats['ytd_high_game_scratch'],
            'high_game_hcp': stats['ytd_high_game_hcp'],
            'high_series_scratch': stats['ytd_high_series_scratch'],
            'high_series_hcp': stats['ytd_high_series_hcp'],
            'games': g,
        })
    return leaders



@reports_bp.route('/season/<int:season_id>/week/<int:week_num>/prizes')
def week_prizes(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week   = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()

    # Regular weekly stats — always computed (tournament weeks show these too)
    prizes = get_weekly_prizes(season_id, week_num)
    all_entries = MatchupEntry.query.filter_by(season_id=season_id, week_num=week_num).all()
    total_wood = sum(
        e.total_pins + (
            (season.blind_handicap if e.is_blind
             else calculate_handicap(e.bowler_id, season_id, week_num))
            * e.game_count
        )
        for e in all_entries
    )
    player_count = sum(1 for e in all_entries if not e.is_blind)
    blind_games  = sum(e.game_count for e in all_entries if e.is_blind)

    min_games = request.args.get('min_games', 9, type=int)
    top10 = request.args.get('top10', 0, type=int)
    roster_entries = (Roster.query
                      .filter_by(season_id=season_id, active=True)
                      .join(Bowler).order_by(Bowler.last_name).all())
    leaders = []
    for r in roster_entries:
        stats = get_bowler_stats(r.bowler_id, season_id, week_num)
        if stats['cumulative_games'] == 0:
            continue
        leaders.append({
            'bowler': r.bowler, 'team': r.team,
            'average':             stats['running_avg'],
            'games':               stats['cumulative_games'],
            'handicap':            stats['display_handicap'],
            'high_game_scratch':   stats['ytd_high_game_scratch'],
            'high_game_hcp':       stats['ytd_high_game_hcp'],
            'high_series_scratch': stats['ytd_high_series_scratch'],
            'high_series_hcp':     stats['ytd_high_series_hcp'],
        })

    avg_rows = sorted(
        [l for l in leaders if l['games'] >= min_games],
        key=lambda x: (-x['average'], x['bowler'].last_name)
    )
    if top10:
        top10_hcps = set(sorted({r['handicap'] for r in avg_rows})[:10])
        avg_rows = [r for r in avg_rows if r['handicap'] in top10_hcps]

    full_year = sorted(get_team_standings(season_id, through_week=week_num), key=lambda s: s['team'].number)
    fh_list = get_team_standings(season_id, half=1, through_week=week_num)
    sh_list = get_team_standings(season_id, half=2, through_week=week_num)
    first_half_map  = {s['team'].id: s['points'] for s in fh_list}
    second_half_map = {s['team'].id: s['points'] for s in sh_list}
    fh_max = max(first_half_map.values(),  default=0)
    sh_max = max(second_half_map.values(), default=0)
    fy_max = max((s['points'] for s in full_year), default=0)

    # Tournament results (post-season weeks only)
    tt = week.tournament_type
    tournament_results = None
    payout = None
    if tt == 'club_championship':
        team_data = {}
        for e in all_entries:
            tid = e.team_id
            if tid not in team_data:
                team_data[tid] = {'team': e.team, 'g1': 0, 'g2': 0, 'g3': 0,
                                  'total_scratch': 0, 'total_wood': 0}
            hcp = (season.blind_handicap if e.is_blind
                   else calculate_handicap(e.bowler_id, season_id, week_num))
            g1, g2, g3 = e.game1 or 0, e.game2 or 0, e.game3 or 0
            team_data[tid]['g1'] += g1
            team_data[tid]['g2'] += g2
            team_data[tid]['g3'] += g3
            team_data[tid]['total_scratch'] += g1 + g2 + g3
            team_data[tid]['total_wood']    += g1 + g2 + g3 + hcp * e.game_count
        tournament_results = sorted(team_data.values(), key=lambda x: -x['total_wood'])
        for i, r in enumerate(tournament_results):
            r['placement'] = i + 1
    elif tt in ('indiv_scratch', 'indiv_hcp_1', 'indiv_hcp_2'):
        t_entries = TournamentEntry.query.filter_by(season_id=season_id, week_num=week_num).all()
        results = []
        for e in t_entries:
            games = [e.game1, e.game2, e.game3, e.game4, e.game5]
            scratch = sum(g for g in games if g is not None)
            total_wood = scratch if tt == 'indiv_scratch' else e.total_with_hcp
            results.append({
                'name':      e.bowler.last_name if e.bowler else e.guest_name,
                'nickname':  e.bowler.nickname  if e.bowler else '',
                'bowler_id': e.bowler_id,
                'games':     games,
                'scratch':   scratch,
                'handicap':  e.handicap,
                'total_wood': total_wood,
            })
        results.sort(key=lambda x: -x['total_wood'])
        for i, r in enumerate(results):
            r['placement'] = i + 1
        tournament_results = results
        payout = PayoutConfig.query.filter_by(season_id=season_id).first()

    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()

    return render_template('reports/week_prizes.html',
                           season=season, week=week, weeks=weeks,
                           prizes=prizes,
                           leaders=leaders,
                           standings=full_year,
                           first_half_map=first_half_map,
                           second_half_map=second_half_map,
                           fh_max=fh_max, sh_max=sh_max, fy_max=fy_max,
                           avg_rows=avg_rows,
                           min_games=min_games,
                           top10=top10,
                           total_wood=total_wood,
                           player_count=player_count,
                           blind_games=blind_games,
                           tournament_type=tt,
                           tournament_results=tournament_results,
                           payout=payout)


@reports_bp.route('/season/<int:season_id>/points')
def team_points(season_id):
    season = Season.query.get_or_404(season_id)
    overall = get_team_standings(season_id)
    first_half = get_team_standings(season_id, half=1)
    second_half = get_team_standings(season_id, half=2)
    weeks_data, standing_teams = get_weekly_team_points(season_id)
    return render_template('reports/team_points.html',
                           season=season,
                           overall=overall,
                           first_half=first_half,
                           second_half=second_half,
                           weeks_data=weeks_data,
                           standing_teams=standing_teams)


@reports_bp.route('/season/<int:season_id>/ytd-alpha/<int:week_num>')
def ytd_alpha(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first()
    rows = get_wkly_alpha(season_id, week_num)
    rows = sorted(rows, key=lambda r: r['bowler'].last_name)
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.number).all()
    team_filter = request.args.get('team', '')
    if team_filter:
        rows = [r for r in rows if r.get('team') and r['team'].name == team_filter]
    return render_template('reports/ytd_alpha.html',
                           season=season, week=week, week_num=week_num,
                           rows=rows, weeks=weeks, teams=teams, team_filter=team_filter)



@reports_bp.route('/season/<int:season_id>/print-batch/<int:week_num>')
def print_batch(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()

    alpha_rows = get_wkly_alpha(season_id, week_num)
    ytd_rows = sorted(alpha_rows, key=lambda r: r['bowler'].last_name)

    # High games data
    last_entered = (Week.query
                    .filter_by(season_id=season_id, is_entered=True)
                    .order_by(Week.week_num.desc())
                    .first())
    hg_through = last_entered.week_num if last_entered else week_num
    min_games = request.args.get('min_games', 9, type=int)
    top10 = request.args.get('top10', 0, type=int)
    hg_leaders = _build_high_games_leaders(season_id, hg_through, min_games=min_games)
    by_avg  = sorted(hg_leaders, key=lambda x: x['average'], reverse=True)
    if top10:
        top10_hcps = set(sorted({r['handicap'] for r in by_avg})[:10])
        by_avg = [r for r in by_avg if r['handicap'] in top10_hcps]
    by_hgs  = sorted(hg_leaders, key=lambda x: x['high_game_scratch'], reverse=True)
    by_hgh  = sorted(hg_leaders, key=lambda x: x['high_game_hcp'], reverse=True)
    by_hss  = sorted(hg_leaders, key=lambda x: x['high_series_scratch'], reverse=True)
    by_hsh  = sorted(hg_leaders, key=lambda x: x['high_series_hcp'], reverse=True)

    # Prizes & Standings data for Group 2 page 4
    prizes = get_weekly_prizes(season_id, week_num)
    all_entries = MatchupEntry.query.filter_by(season_id=season_id, week_num=week_num).all()
    total_wood = sum(
        e.total_pins + (
            (season.blind_handicap if e.is_blind
             else calculate_handicap(e.bowler_id, season_id, week_num))
            * e.game_count
        )
        for e in all_entries
    )
    player_count = sum(1 for e in all_entries if not e.is_blind)
    blind_games = sum(e.game_count for e in all_entries if e.is_blind)
    pb_full_year   = sorted(get_team_standings(season_id, through_week=week_num), key=lambda s: s['team'].number)
    pb_fh_list     = get_team_standings(season_id, half=1, through_week=week_num)
    pb_sh_list     = get_team_standings(season_id, half=2, through_week=week_num)
    pb_first_half  = {s['team'].id: s['points'] for s in pb_fh_list}
    pb_second_half = {s['team'].id: s['points'] for s in pb_sh_list}
    pb_fh_max = max(pb_first_half.values(),  default=0)
    pb_sh_max = max(pb_second_half.values(), default=0)
    pb_fy_max = max((s['points'] for s in pb_full_year),   default=0)

    return render_template('reports/print_batch.html',
                           season=season, week=week, week_num=week_num, weeks=weeks,
                           alpha_rows=alpha_rows,
                           ytd_rows=ytd_rows,
                           by_avg=by_avg, by_hgs=by_hgs, by_hgh=by_hgh,
                           by_hss=by_hss, by_hsh=by_hsh,
                           hg_through=hg_through,
                           min_games=min_games, top10=top10,
                           prizes=prizes,
                           pb_leaders=hg_leaders,
                           week_standings=pb_full_year,
                           pb_first_half=pb_first_half,
                           pb_second_half=pb_second_half,
                           pb_fh_max=pb_fh_max, pb_sh_max=pb_sh_max, pb_fy_max=pb_fy_max,
                           total_wood=total_wood,
                           player_count=player_count,
                           blind_games=blind_games)

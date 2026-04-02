"""
Report routes: Wkly Alpha (printable), standings, bowler detail, high games.
"""

from flask import Blueprint, render_template, request, redirect, url_for
from models import Season, Week, Roster, Bowler, Team, MatchupEntry, TeamPoints
from calculations import (get_wkly_alpha, get_team_standings, get_bowler_stats,
                           get_iron_man_status, get_most_improved, get_weekly_prizes,
                           calculate_handicap, get_weekly_team_points, get_matchup_breakdown)
from models import MatchupEntry

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/season/<int:season_id>/alpha/<int:week_num>')
def wkly_alpha(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first()
    rows = get_wkly_alpha(season_id, week_num)
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()
    return render_template('reports/wkly_alpha.html',
                           season=season, week=week, week_num=week_num,
                           rows=rows, weeks=weeks)



@reports_bp.route('/season/<int:season_id>/bowler/<int:bowler_id>')
def bowler_detail(season_id, bowler_id):
    season = Season.query.get_or_404(season_id)
    bowler = Bowler.query.get_or_404(bowler_id)
    stats = get_bowler_stats(bowler_id, season_id)
    roster = Roster.query.filter_by(bowler_id=bowler_id, season_id=season_id).first()
    return render_template('reports/bowler_detail.html',
                           season=season, bowler=bowler,
                           stats=stats, roster=roster)


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

    # YTD high game/series leaders through this week
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

    # Averages table: filter by min_games, sort by avg desc
    avg_rows = sorted(
        [l for l in leaders if l['games'] >= min_games],
        key=lambda x: (-x['average'], x['bowler'].last_name)
    )
    if top10:
        top10_hcps = set(sorted({r['handicap'] for r in avg_rows})[:10])
        avg_rows = [r for r in avg_rows if r['handicap'] in top10_hcps]

    full_year = sorted(get_team_standings(season_id, through_week=week_num), key=lambda s: s['team'].number)
    first_half_s = sorted(get_team_standings(season_id, half=1), key=lambda s: s['team'].number)
    second_half_s = sorted(get_team_standings(season_id, half=2), key=lambda s: s['team'].number)
    fh_max = max((s['points'] for s in first_half_s), default=0)
    sh_max = max((s['points'] for s in second_half_s), default=0)
    fy_max = max((s['points'] for s in full_year), default=0)

    return render_template('reports/week_prizes.html',
                           season=season, week=week,
                           prizes=prizes,
                           leaders=leaders,
                           standings=full_year,
                           first_half_s=first_half_s,
                           second_half_s=second_half_s,
                           fh_max=fh_max, sh_max=sh_max, fy_max=fy_max,
                           avg_rows=avg_rows,
                           min_games=min_games,
                           top10=top10,
                           total_wood=total_wood,
                           player_count=player_count,
                           blind_games=blind_games)


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
    return render_template('reports/ytd_alpha.html',
                           season=season, week=week, week_num=week_num,
                           rows=rows, weeks=weeks)



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
    hg_leaders = _build_high_games_leaders(season_id, hg_through)
    by_avg  = sorted(hg_leaders, key=lambda x: x['average'], reverse=True)
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
    pb_first_half  = sorted(get_team_standings(season_id, half=1), key=lambda s: s['team'].number)
    pb_second_half = sorted(get_team_standings(season_id, half=2), key=lambda s: s['team'].number)
    pb_fh_max = max((s['points'] for s in pb_first_half),  default=0)
    pb_sh_max = max((s['points'] for s in pb_second_half), default=0)
    pb_fy_max = max((s['points'] for s in pb_full_year),   default=0)

    return render_template('reports/print_batch.html',
                           season=season, week=week, week_num=week_num, weeks=weeks,
                           alpha_rows=alpha_rows,
                           ytd_rows=ytd_rows,
                           by_avg=by_avg, by_hgs=by_hgs, by_hgh=by_hgh,
                           by_hss=by_hss, by_hsh=by_hsh,
                           hg_through=hg_through,
                           prizes=prizes,
                           pb_leaders=hg_leaders,
                           week_standings=pb_full_year,
                           pb_first_half=pb_first_half,
                           pb_second_half=pb_second_half,
                           pb_fh_max=pb_fh_max, pb_sh_max=pb_sh_max, pb_fy_max=pb_fy_max,
                           total_wood=total_wood,
                           player_count=player_count,
                           blind_games=blind_games)

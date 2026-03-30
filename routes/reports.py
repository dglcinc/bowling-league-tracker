"""
Report routes: Wkly Alpha (printable), standings, bowler detail, high games.
"""

from flask import Blueprint, render_template, request, redirect, url_for
from models import Season, Week, Roster, Bowler, Team, MatchupEntry, TeamPoints
from calculations import (get_wkly_alpha, get_team_standings, get_bowler_stats,
                           get_iron_man_status, get_most_improved, get_weekly_prizes,
                           calculate_handicap, get_weekly_team_points)
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


@reports_bp.route('/season/<int:season_id>/standings')
def standings(season_id):
    season = Season.query.get_or_404(season_id)
    overall = get_team_standings(season_id)
    first_half = get_team_standings(season_id, half=1)
    second_half = get_team_standings(season_id, half=2)
    weeks_data, teams = get_weekly_team_points(season_id)
    return render_template('reports/standings.html',
                           season=season,
                           overall=overall,
                           first_half=first_half,
                           second_half=second_half,
                           weeks_data=weeks_data,
                           teams=teams)


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


@reports_bp.route('/season/<int:season_id>/high-games')
def high_games(season_id):
    season = Season.query.get_or_404(season_id)
    through_week = request.args.get('week', type=int)
    min_games = request.args.get('min_games', 0, type=int)
    if not through_week:
        last = (Week.query
                .filter_by(season_id=season_id, is_entered=True)
                .order_by(Week.week_num.desc())
                .first())
        through_week = last.week_num if last else 0

    leaders = _build_high_games_leaders(season_id, through_week, min_games)

    by_avg = sorted(leaders, key=lambda x: x['average'], reverse=True)
    by_hgs = sorted(leaders, key=lambda x: x['high_game_scratch'], reverse=True)
    by_hgh = sorted(leaders, key=lambda x: x['high_game_hcp'], reverse=True)
    by_hss = sorted(leaders, key=lambda x: x['high_series_scratch'], reverse=True)
    by_hsh = sorted(leaders, key=lambda x: x['high_series_hcp'], reverse=True)

    return render_template('reports/high_games.html',
                           season=season, through_week=through_week,
                           min_games=min_games,
                           by_avg=by_avg, by_hgs=by_hgs, by_hgh=by_hgh,
                           by_hss=by_hss, by_hsh=by_hsh)


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
            'average':           stats['running_avg'],
            'high_game_scratch': stats['ytd_high_game_scratch'],
            'high_game_hcp':     stats['ytd_high_game_hcp'],
            'high_series_scratch': stats['ytd_high_series_scratch'],
            'high_series_hcp':   stats['ytd_high_series_hcp'],
        })

    standings = get_team_standings(season_id, through_week=week_num)

    return render_template('reports/week_prizes.html',
                           season=season, week=week,
                           prizes=prizes,
                           leaders=leaders,
                           standings=standings,
                           total_wood=total_wood,
                           player_count=player_count,
                           blind_games=blind_games)


@reports_bp.route('/season/<int:season_id>/ytd-alpha/<int:week_num>')
def ytd_alpha(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first()
    rows = get_wkly_alpha(season_id, week_num)
    rows = sorted(rows, key=lambda r: (-r['average'], r['bowler'].last_name))
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()
    return render_template('reports/ytd_alpha.html',
                           season=season, week=week, week_num=week_num,
                           rows=rows, weeks=weeks)


@reports_bp.route('/season/<int:season_id>/high-avg/<int:week_num>')
def wkly_high_avg(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first()
    rows = get_wkly_alpha(season_id, week_num)
    rows = sorted(rows, key=lambda r: (-r['average'], r['bowler'].last_name))
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()
    return render_template('reports/wkly_high_avg.html',
                           season=season, week=week, week_num=week_num,
                           rows=rows, weeks=weeks)


@reports_bp.route('/season/<int:season_id>/print-batch/<int:week_num>')
def print_batch(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()

    alpha_rows = get_wkly_alpha(season_id, week_num)
    high_avg_rows = sorted(alpha_rows, key=lambda r: (-r['average'], r['bowler'].last_name))
    ytd_rows = high_avg_rows  # same data, same sort; different columns in template

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

    return render_template('reports/print_batch.html',
                           season=season, week=week, week_num=week_num, weeks=weeks,
                           alpha_rows=alpha_rows,
                           high_avg_rows=high_avg_rows,
                           ytd_rows=ytd_rows,
                           by_avg=by_avg, by_hgs=by_hgs, by_hgh=by_hgh,
                           by_hss=by_hss, by_hsh=by_hsh,
                           hg_through=hg_through)

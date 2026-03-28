"""
Report routes: Wkly Alpha (printable), standings, bowler detail, high games.
"""

from flask import Blueprint, render_template, request, redirect, url_for
from models import Season, Week, Roster, Bowler, Team, MatchupEntry, TeamPoints
from calculations import (get_wkly_alpha, get_team_standings, get_bowler_stats,
                           get_iron_man_status, get_most_improved)

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
    half = request.args.get('half', type=int)
    overall = get_team_standings(season_id)
    first_half = get_team_standings(season_id, half=1)
    second_half = get_team_standings(season_id, half=2)
    return render_template('reports/standings.html',
                           season=season,
                           overall=overall,
                           first_half=first_half,
                           second_half=second_half)


@reports_bp.route('/season/<int:season_id>/bowler/<int:bowler_id>')
def bowler_detail(season_id, bowler_id):
    season = Season.query.get_or_404(season_id)
    bowler = Bowler.query.get_or_404(bowler_id)
    stats = get_bowler_stats(bowler_id, season_id)
    roster = Roster.query.filter_by(bowler_id=bowler_id, season_id=season_id).first()
    return render_template('reports/bowler_detail.html',
                           season=season, bowler=bowler,
                           stats=stats, roster=roster)


@reports_bp.route('/season/<int:season_id>/high-games')
def high_games(season_id):
    season = Season.query.get_or_404(season_id)
    through_week = request.args.get('week', type=int)
    if not through_week:
        last = (Week.query
                .filter_by(season_id=season_id, is_entered=True)
                .order_by(Week.week_num.desc())
                .first())
        through_week = last.week_num if last else 0

    roster_entries = (Roster.query
                      .filter_by(season_id=season_id, active=True)
                      .join(Bowler)
                      .order_by(Bowler.last_name)
                      .all())

    leaders = []
    for r in roster_entries:
        stats = get_bowler_stats(r.bowler_id, season_id, through_week)
        if stats['cumulative_games'] == 0:
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
            'games': stats['cumulative_games'],
        })

    by_avg = sorted(leaders, key=lambda x: x['average'], reverse=True)
    by_hgs = sorted(leaders, key=lambda x: x['high_game_scratch'], reverse=True)
    by_hgh = sorted(leaders, key=lambda x: x['high_game_hcp'], reverse=True)
    by_hss = sorted(leaders, key=lambda x: x['high_series_scratch'], reverse=True)
    by_hsh = sorted(leaders, key=lambda x: x['high_series_hcp'], reverse=True)

    return render_template('reports/high_games.html',
                           season=season, through_week=through_week,
                           by_avg=by_avg, by_hgs=by_hgs, by_hgh=by_hgh,
                           by_hss=by_hss, by_hsh=by_hsh)

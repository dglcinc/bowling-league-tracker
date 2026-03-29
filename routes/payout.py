"""
Payout tracker routes: prize standings, iron man, most improved.
"""

from flask import Blueprint, render_template
from models import Season, Week, Roster, Bowler, MatchupEntry
from calculations import get_iron_man_status, get_most_improved, get_bowler_stats

payout_bp = Blueprint('payout', __name__)


@payout_bp.route('/season/<int:season_id>')
def payout_overview(season_id):
    season = Season.query.get_or_404(season_id)
    last = (Week.query
            .filter_by(season_id=season_id, is_entered=True)
            .order_by(Week.week_num.desc())
            .first())
    through_week = last.week_num if last else 0

    iron_men = get_iron_man_status(season_id, through_week)
    most_improved = get_most_improved(season_id, through_week)

    # Weekly high game scratch leaders by week
    weekly_high = []
    entered_weeks = (Week.query
                     .filter_by(season_id=season_id, is_entered=True)
                     .order_by(Week.week_num)
                     .all())

    for wk in entered_weeks:
        entries = (MatchupEntry.query
                   .filter_by(season_id=season_id, week_num=wk.week_num, is_blind=False)
                   .all())
        if not entries:
            continue
        best = None
        best_score = 0
        for e in entries:
            for g in e.all_games:
                if g and g > best_score:
                    best_score = g
                    best = e
        if best and best.bowler:
            weekly_high.append({
                'week_num': wk.week_num,
                'bowler': best.bowler,
                'score': best_score,
            })

    return render_template('payout/overview.html',
                           season=season,
                           through_week=through_week,
                           iron_men=iron_men,
                           most_improved=most_improved,
                           weekly_high=weekly_high)

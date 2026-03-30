"""
Payout tracker routes: weekly prizes, prize totals, iron man, most improved.
"""

from flask import Blueprint, render_template
from models import Season, Week, Roster, Bowler
from calculations import (get_iron_man_status, get_most_improved, get_bowler_stats,
                          get_weekly_prizes)

payout_bp = Blueprint('payout', __name__)

PRIZE_KEYS = [
    ('hg_scratch', 'HG Scratch'),
    ('hg_hcp',     'HG Handicap'),
    ('hs_scratch', 'HS Scratch'),
    ('hs_hcp',     'HS Handicap'),
]


@payout_bp.route('/season/<int:season_id>')
def payout_overview(season_id):
    season = Season.query.get_or_404(season_id)
    entered_weeks = (Week.query
                     .filter_by(season_id=season_id, is_entered=True, is_cancelled=False)
                     .order_by(Week.week_num)
                     .all())
    through_week = entered_weeks[-1].week_num if entered_weeks else 0

    # Weekly prizes for every entered week
    weekly_prizes = []
    prize_counts = {}   # bowler_id -> {key -> count}

    for wk in entered_weeks:
        prizes = get_weekly_prizes(season_id, wk.week_num)
        if not prizes:
            continue
        weekly_prizes.append({'week': wk, 'prizes': prizes})
        for key, _ in PRIZE_KEYS:
            for w in prizes[key]['winners']:
                bid = w['bowler'].id
                if bid not in prize_counts:
                    prize_counts[bid] = {k: 0 for k, _ in PRIZE_KEYS}
                prize_counts[bid][key] += 1

    # Build YTD prize totals per bowler (only those with at least one prize)
    roster = Roster.query.filter_by(season_id=season_id, active=True).all()
    ytd_prizes = []
    for r in roster:
        counts = prize_counts.get(r.bowler_id)
        if not counts:
            continue
        total = sum(counts.values())
        ytd_prizes.append({
            'bowler': r.bowler,
            'team':   r.team,
            'counts': counts,
            'total':  total,
        })
    ytd_prizes.sort(key=lambda x: x['total'], reverse=True)

    iron_men     = get_iron_man_status(season_id, through_week)
    most_improved = get_most_improved(season_id, through_week)

    return render_template('payout/overview.html',
                           season=season,
                           through_week=through_week,
                           weekly_prizes=weekly_prizes,
                           ytd_prizes=ytd_prizes,
                           prize_keys=PRIZE_KEYS,
                           iron_men=iron_men,
                           most_improved=most_improved)

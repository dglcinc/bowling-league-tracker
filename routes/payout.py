"""
Payout routes: weekly prize overview, season payout config, summary, and award pages.
"""

import json
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Season, Week, Roster, Bowler, Team, TournamentEntry, PayoutConfig
from calculations import (get_iron_man_status, get_most_improved, get_bowler_stats,
                          get_weekly_prizes, get_team_standings)

payout_bp = Blueprint('payout', __name__)

PRIZE_KEYS = [
    ('hg_scratch', 'HG Scratch',  'High Game — Scratch'),
    ('hg_hcp',     'HG Handicap', 'High Game — Handicap'),
    ('hs_scratch', 'HS Scratch',  'High Series — Scratch'),
    ('hs_hcp',     'HS Handicap', 'High Series — Handicap'),
]

YTD_CATS = [
    ('ytd_high_game_scratch',   'YTD High Game — Scratch'),
    ('ytd_high_game_hcp',       'YTD High Game — Handicap'),
    ('ytd_high_series_scratch', 'YTD High Series — Scratch'),
    ('ytd_high_series_hcp',     'YTD High Series — Handicap'),
]

PLACE_LABELS = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _currency_breakdown(amount):
    """Return bill counts for an amount (whole dollars, greedy largest-first)."""
    remaining = max(0, int(round(float(amount))))
    result = {}
    for denom in [100, 50, 20, 10, 5, 1]:
        count = remaining // denom
        result[denom] = count
        remaining -= count * denom
    return result


def _calculate_payout(season_id, config):
    """
    Build the full payout waterfall for a season.

    Returns a dict with keys:
      total_available, tournament_items, tournament_total,
      individual_payouts (list sorted by last_name), individual_total,
      trophy_cost, team_payouts, team_total, remainder, final_week
    """
    season = Season.query.get(season_id)

    # ---- 1. TOURNAMENT AWARDS ----
    tournament_weeks = (Week.query
                        .filter_by(season_id=season_id, is_entered=True)
                        .filter(Week.tournament_type.isnot(None))
                        .order_by(Week.week_num)
                        .all())

    tournament_items = []  # one dict per place per tournament
    for tw in tournament_weeks:
        entries = (TournamentEntry.query
                   .filter_by(season_id=season_id, week_num=tw.week_num)
                   .all())
        if not entries:
            continue
        ranked = sorted(entries, key=lambda e: e.total_with_hcp, reverse=True)
        prize_amts = [config.tournament_prize_1,
                      config.tournament_prize_2,
                      config.tournament_prize_3]
        for i, (entry, amt) in enumerate(zip(ranked[:3], prize_amts)):
            if amt <= 0:
                continue
            tournament_items.append({
                'bowler':          entry.bowler,         # None for guest
                'guest_name':      entry.guest_name,
                'display_name':    entry.display_name,
                'place':           PLACE_LABELS[i],
                'place_num':       i + 1,
                'score':           entry.total_with_hcp,
                'amount':          amt,
                'week_num':        tw.week_num,
                'tournament_type': tw.tournament_type,
            })

    tournament_total = sum(item['amount'] for item in tournament_items)

    # ---- 2. INDIVIDUAL WEEKLY PRIZES ----
    regular_weeks = (Week.query
                     .filter_by(season_id=season_id, is_entered=True, is_cancelled=False)
                     .filter(Week.tournament_type.is_(None))
                     .order_by(Week.week_num)
                     .all())

    # ind_map[bowler_id] = {'bowler', 'team', 'prizes': [], 'total'}
    ind_map = {}

    def _get_ind(bowler, team):
        bid = bowler.id
        if bid not in ind_map:
            ind_map[bid] = {'bowler': bowler, 'team': team, 'prizes': [], 'total': 0.0}
        return ind_map[bid]

    for wk in regular_weeks:
        prizes = get_weekly_prizes(season_id, wk.week_num)
        if not prizes:
            continue
        for key, short_label, long_label in PRIZE_KEYS:
            cat = prizes[key]
            for w in cat['winners']:
                bowler = w['bowler']
                roster = Roster.query.filter_by(
                    bowler_id=bowler.id, season_id=season_id).first()
                team = roster.team if roster else None
                rec = _get_ind(bowler, team)
                rec['prizes'].append({
                    'type':     'weekly',
                    'week_num': wk.week_num,
                    'label':    long_label,
                    'score':    cat['score'],
                    'amount':   config.weekly_win_rate,
                })
                rec['total'] += config.weekly_win_rate

    # ---- 3. YTD PRIZES ----
    final_week = config.final_week
    roster_entries = Roster.query.filter_by(season_id=season_id, active=True).all()

    for stat_key, label in YTD_CATS:
        best_score = -1
        best_list = []
        for r in roster_entries:
            stats = get_bowler_stats(r.bowler_id, season_id, final_week)
            if stats['cumulative_games'] == 0:
                continue
            score = stats[stat_key]
            if score > best_score:
                best_score = score
                best_list = [(r.bowler, r.team, score)]
            elif score == best_score and score > 0:
                best_list.append((r.bowler, r.team, score))

        for bowler, team, score in best_list:
            rec = _get_ind(bowler, team)
            rec['prizes'].append({
                'type':   'ytd',
                'label':  label,
                'score':  score,
                'amount': config.ytd_prize_rate,
            })
            rec['total'] += config.ytd_prize_rate

    # ---- 4. MOST IMPROVED ----
    improved = get_most_improved(season_id, final_week)
    eligible = [x for x in improved
                if x['improvement'] is not None and x['improvement'] > 0]
    if eligible:
        best = eligible[0]
        bowler = best['bowler']
        roster_entry = Roster.query.filter_by(
            bowler_id=bowler.id, season_id=season_id).first()
        team = roster_entry.team if roster_entry else None
        rec = _get_ind(bowler, team)
        rec['prizes'].append({
            'type':        'most_improved',
            'label':       'Most Improved',
            'improvement': best['improvement'],
            'prior_avg':   best['prior_avg'],
            'current_avg': best['current_avg'],
            'description': (f"improved {best['improvement']} pins per game "
                            f"(avg {best['prior_avg']} \u2192 {best['current_avg']})"),
            'amount':      config.ytd_prize_rate,
        })
        rec['total'] += config.ytd_prize_rate

    individual_total = sum(p['total'] for p in ind_map.values())

    # ---- 5. TEAM REMAINDER ----
    remainder = (config.total_available
                 - tournament_total
                 - individual_total
                 - config.trophy_cost)

    try:
        team_pcts = json.loads(config.team_pct_json)
    except (ValueError, TypeError):
        team_pcts = [40, 30, 20, 10]

    standings = get_team_standings(season_id)
    team_payouts = []
    for i, standing in enumerate(standings):
        pct = team_pcts[i] if i < len(team_pcts) else 0
        amount = round(remainder * pct / 100, 2)
        # Find team captain from roster
        captain = None
        for r in Roster.query.filter_by(
                season_id=season_id, team_id=standing['team'].id, active=True).all():
            if r.team.captain_name:
                captain = r.team.captain_name
                break
        team_payouts.append({
            'team':      standing['team'],
            'captain':   captain or standing['team'].captain_name,
            'place':     PLACE_LABELS[i] if i < len(PLACE_LABELS) else f'{i+1}th',
            'place_num': i + 1,
            'points':    standing['points'],
            'pct':       pct,
            'amount':    amount,
        })
    team_total = sum(tp['amount'] for tp in team_payouts)

    # Sort individual payouts alphabetically
    individual_payouts = sorted(ind_map.values(),
                                key=lambda x: x['bowler'].last_name)

    return {
        'total_available':   config.total_available,
        'tournament_items':  tournament_items,
        'tournament_total':  tournament_total,
        'individual_payouts': individual_payouts,
        'individual_total':  individual_total,
        'trophy_cost':       config.trophy_cost,
        'team_payouts':      team_payouts,
        'team_total':        team_total,
        'remainder':         remainder,
        'final_week':        final_week,
    }


def _build_recipients(payout):
    """
    Build the list of recipient dicts used by the award page template.
    Each dict is self-contained for rendering one certificate.
    """
    recipients = []

    # Individual recipients
    for ind in payout['individual_payouts']:
        bowler = ind['bowler']
        team = ind['team']
        recipients.append({
            'type':       'individual',
            'bowler':     bowler,
            'name':       bowler.last_name,
            'first_name': bowler.first_name or '',
            'nickname':   bowler.nickname or '',
            'team_label': (f"Team {team.number} \u2014 {team.name}"
                           if team else ''),
            'prizes':      ind['prizes'],
            'total':      ind['total'],
        })

    # Tournament winners who are guests (no bowler record)
    guest_tourney = [t for t in payout['tournament_items'] if t['bowler'] is None]
    # (guests don't get individual award pages since they have no bowler record)

    # Team recipients
    for tp in payout['team_payouts']:
        team = tp['team']
        recipients.append({
            'type':      'team',
            'team':      team,
            'name':      f"Team {team.number} \u2014 {team.name}",
            'captain':   team.captain_name or '',
            'place':     tp['place'],
            'points':    tp['points'],
            'prizes': [{
                'type':   'team_finish',
                'label':  f"Season {tp['place']} Place",
                'detail': f"{tp['points']} points",
                'amount': tp['amount'],
            }],
            'total': tp['amount'],
        })

    return recipients


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@payout_bp.route('/season/<int:season_id>')
def payout_overview(season_id):
    season = Season.query.get_or_404(season_id)
    entered_weeks = (Week.query
                     .filter_by(season_id=season_id, is_entered=True, is_cancelled=False)
                     .filter(Week.tournament_type.is_(None))
                     .order_by(Week.week_num)
                     .all())
    through_week = entered_weeks[-1].week_num if entered_weeks else 0

    weekly_prizes = []
    prize_counts = {}   # bowler_id -> {key -> count}

    for wk in entered_weeks:
        prizes = get_weekly_prizes(season_id, wk.week_num)
        if not prizes:
            continue
        weekly_prizes.append({'week': wk, 'prizes': prizes})
        for key, _, _ in PRIZE_KEYS:
            for w in prizes[key]['winners']:
                bid = w['bowler'].id
                if bid not in prize_counts:
                    prize_counts[bid] = {k: 0 for k, _, _ in PRIZE_KEYS}
                prize_counts[bid][key] += 1

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
    config = PayoutConfig.query.filter_by(season_id=season_id).first()

    return render_template('payout/overview.html',
                           season=season,
                           through_week=through_week,
                           weekly_prizes=weekly_prizes,
                           ytd_prizes=ytd_prizes,
                           prize_keys=[(k, s) for k, s, l in PRIZE_KEYS],
                           iron_men=iron_men,
                           most_improved=most_improved,
                           config=config)


@payout_bp.route('/season/<int:season_id>/config', methods=['GET', 'POST'])
def payout_config(season_id):
    season = Season.query.get_or_404(season_id)
    config = PayoutConfig.query.filter_by(season_id=season_id).first()
    if config is None:
        config = PayoutConfig(season_id=season_id)
        db.session.add(config)
        db.session.commit()

    if request.method == 'POST':
        config.total_available    = float(request.form.get('total_available', 0))
        config.tournament_prize_1 = float(request.form.get('tournament_prize_1', 125))
        config.tournament_prize_2 = float(request.form.get('tournament_prize_2', 100))
        config.tournament_prize_3 = float(request.form.get('tournament_prize_3', 75))
        config.weekly_win_rate    = float(request.form.get('weekly_win_rate', 10))
        config.ytd_prize_rate     = float(request.form.get('ytd_prize_rate', 75))
        config.trophy_cost        = float(request.form.get('trophy_cost', 125))
        config.final_week         = int(request.form.get('final_week', 22))

        pct_raw = request.form.get('team_pcts', '40,30,20,10')
        try:
            pcts = [float(x.strip()) for x in pct_raw.split(',') if x.strip()]
            config.team_pct_json = json.dumps(pcts)
        except ValueError:
            flash('Team percentages must be comma-separated numbers.', 'warning')
            return redirect(url_for('payout.payout_config', season_id=season_id))

        db.session.commit()
        return redirect(url_for('payout.payout_summary', season_id=season_id))

    try:
        team_pcts_str = ', '.join(str(int(x)) for x in json.loads(config.team_pct_json))
    except (ValueError, TypeError):
        team_pcts_str = '40, 30, 20, 10'

    return render_template('payout/config.html',
                           season=season,
                           config=config,
                           team_pcts_str=team_pcts_str)


@payout_bp.route('/season/<int:season_id>/summary')
def payout_summary(season_id):
    season = Season.query.get_or_404(season_id)
    config = PayoutConfig.query.filter_by(season_id=season_id).first()
    if config is None or config.total_available == 0:
        return redirect(url_for('payout.payout_config', season_id=season_id))

    payout = _calculate_payout(season_id, config)

    # Build currency breakdown per individual payee
    breakdowns = {}
    for ind in payout['individual_payouts']:
        bid = ind['bowler'].id
        breakdowns[bid] = _currency_breakdown(ind['total'])

    # Team payouts currency breakdown
    team_breakdowns = {}
    for tp in payout['team_payouts']:
        team_breakdowns[tp['team'].id] = _currency_breakdown(tp['amount'])

    # Tournament payees (only league members, not guests)
    tourney_breakdowns = {}
    for item in payout['tournament_items']:
        if item['bowler']:
            bid = item['bowler'].id
            existing = tourney_breakdowns.get(bid, {})
            bd = _currency_breakdown(item['amount'])
            for denom, count in bd.items():
                existing[denom] = existing.get(denom, 0) + count
            tourney_breakdowns[bid] = existing

    # Aggregate bank inventory (all payees combined)
    agg = {d: 0 for d in [100, 50, 20, 10, 5, 1]}
    for bd in list(breakdowns.values()) + list(team_breakdowns.values()):
        for d, cnt in bd.items():
            agg[d] += cnt
    for bd in tourney_breakdowns.values():
        for d, cnt in bd.items():
            agg[d] += cnt

    return render_template('payout/summary.html',
                           season=season,
                           payout=payout,
                           breakdowns=breakdowns,
                           team_breakdowns=team_breakdowns,
                           tourney_breakdowns=tourney_breakdowns,
                           agg=agg,
                           denoms=[100, 50, 20, 10, 5, 1])


@payout_bp.route('/season/<int:season_id>/award/all')
def award_all(season_id):
    season = Season.query.get_or_404(season_id)
    config = PayoutConfig.query.filter_by(season_id=season_id).first()
    if config is None or config.total_available == 0:
        return redirect(url_for('payout.payout_config', season_id=season_id))
    payout = _calculate_payout(season_id, config)
    recipients = _build_recipients(payout)
    return render_template('payout/award_page.html',
                           season=season,
                           recipients=recipients,
                           single=False)


@payout_bp.route('/season/<int:season_id>/award/bowler/<int:bowler_id>')
def award_bowler(season_id, bowler_id):
    season = Season.query.get_or_404(season_id)
    config = PayoutConfig.query.filter_by(season_id=season_id).first()
    if config is None or config.total_available == 0:
        return redirect(url_for('payout.payout_config', season_id=season_id))
    payout = _calculate_payout(season_id, config)
    recipients = [r for r in _build_recipients(payout)
                  if r['type'] == 'individual' and r['bowler'].id == bowler_id]
    if not recipients:
        return redirect(url_for('payout.payout_summary', season_id=season_id))
    return render_template('payout/award_page.html',
                           season=season,
                           recipients=recipients,
                           single=True)


@payout_bp.route('/season/<int:season_id>/award/team/<int:team_id>')
def award_team(season_id, team_id):
    season = Season.query.get_or_404(season_id)
    config = PayoutConfig.query.filter_by(season_id=season_id).first()
    if config is None or config.total_available == 0:
        return redirect(url_for('payout.payout_config', season_id=season_id))
    payout = _calculate_payout(season_id, config)
    recipients = [r for r in _build_recipients(payout)
                  if r['type'] == 'team' and r['team'].id == team_id]
    if not recipients:
        return redirect(url_for('payout.payout_summary', season_id=season_id))
    return render_template('payout/award_page.html',
                           season=season,
                           recipients=recipients,
                           single=True)

"""
Payout routes: weekly prize overview, season payout config, summary, and award pages.
"""

import json
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import (db, Season, Week, Roster, Bowler, Team, TournamentEntry,
                    PayoutConfig, TeamPoints, LeagueSettings)
from calculations import (get_iron_man_status, get_most_improved, get_bowler_stats,
                          get_weekly_prizes, get_team_standings, build_leaders_list)

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


def _split_whole_dollars(total_amount, pcts):
    """
    Split `total_amount` across `pcts` (a list of percentages) as whole-dollar
    integers. Sum of the result equals int(round(total_amount)). Any leftover
    dollars from rounding go to higher-ranked (lower-index) positions first,
    so a tie or fractional cent rounds up for the better-ranked team.

    Example: split $487 by [35, 25, 20, 20] →
      exact: 170.45, 121.75, 97.40, 97.40
      floor: 170,    121,    97,    97  (sum=485, leftover=2)
      result: 171,   122,    97,    97  (sum=487)
    """
    total = int(round(float(total_amount or 0)))
    if total <= 0 or not pcts:
        return [0] * len(pcts)
    exacts = [total * float(pct) / 100.0 for pct in pcts]
    result = [int(e) for e in exacts]  # floor
    leftover = total - sum(result)
    i = 0
    while leftover > 0:
        result[i % len(result)] += 1
        leftover -= 1
        i += 1
    return result


def _calculate_payout(season_id, config):
    """
    Build the full payout waterfall for a season.

    Returns a dict with keys:
      total_available, tournament_items, tournament_total,
      individual_payouts (list sorted by last_name), individual_total,
      trophy_cost, team_payouts, team_total, remainder, final_week
    """
    season = db.session.get(Season, season_id)

    # ---- 1. TOURNAMENT AWARDS ----
    tournament_weeks = (Week.query
                        .filter_by(season_id=season_id, is_entered=True)
                        .filter(Week.tournament_type.isnot(None))
                        .order_by(Week.week_num)
                        .all())

    tournament_labels = season.tournament_labels or {}

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
                'bowler':           entry.bowler,         # None for guest
                'guest_name':       entry.guest_name,
                'display_name':     entry.display_name,
                'place':            PLACE_LABELS[i],
                'place_num':        i + 1,
                'score':            entry.total_with_hcp,
                'amount':           amt,
                'week_num':         tw.week_num,
                'tournament_type':  tw.tournament_type,
                'tournament_label': tournament_labels.get(tw.tournament_type, tw.tournament_type),
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

    # individual_total = waterfall figure — weekly + YTD + MI only,
    # NOT tournament prizes (which have their own waterfall line).
    individual_total = sum(p['total'] for p in ind_map.values())

    # ---- 4b. ATTACH TOURNAMENT PRIZES TO ROSTERED BOWLERS ----
    # Guests (no bowler record) stay only in tournament_items — they don't get
    # an individual payout row or award certificate. Rostered tournament winners
    # also need their tournament prize on their certificate and in the cash total,
    # so we fold those into ind_map here. ind['total'] now reflects the full
    # cash payout to the bowler; individual_total (above) stays unchanged so the
    # waterfall doesn't double-count tournament prizes.
    for item in tournament_items:
        bowler = item['bowler']
        if bowler is None:
            continue
        roster = Roster.query.filter_by(
            bowler_id=bowler.id, season_id=season_id).first()
        team = roster.team if roster else None
        rec = _get_ind(bowler, team)
        rec['prizes'].append({
            'type':             'tournament',
            'week_num':         item['week_num'],
            'tournament_type':  item['tournament_type'],
            'tournament_label': item['tournament_label'],
            'place':            item['place'],
            'label':            f"{item['tournament_label']} — {item['place']}",
            'score':            item['score'],
            'amount':           item['amount'],
        })
        rec['total'] += item['amount']

    # ---- 4c. HIGH AVERAGE PRIZE ----
    # Top-3 season averages among rostered bowlers meeting the league's
    # minimum-games threshold (same filter the weekly prizes page uses).
    # Pays its own fixed amounts (defaults match the tournament prizes) and,
    # like tournament prizes, gets its own waterfall line — folded into
    # ind_map *after* individual_total so the waterfall doesn't double-count.
    settings = db.session.get(LeagueSettings, 1)
    min_games = (settings.prizes_min_games
                 if settings and settings.prizes_min_games is not None else 9)
    _, avg_rows = build_leaders_list(season_id, final_week, min_games=min_games)

    high_avg_prizes = [config.high_avg_prize_1,
                       config.high_avg_prize_2,
                       config.high_avg_prize_3]
    high_avg_items = []  # one dict per place, for the summary page
    for i, (row, amt) in enumerate(zip(avg_rows[:3], high_avg_prizes)):
        if amt <= 0:
            continue
        bowler = row['bowler']
        team = row['team']
        high_avg_items.append({
            'bowler':     bowler,
            'team':       team,
            'place':      PLACE_LABELS[i],
            'place_num':  i + 1,
            'average':    row['average'],
            'games':      row['games'],
            'amount':     amt,
        })
        rec = _get_ind(bowler, team)
        rec['prizes'].append({
            'type':   'high_avg',
            'place':  PLACE_LABELS[i],
            'label':  f"High Average — {PLACE_LABELS[i]} Place",
            'score':  row['average'],
            'amount': amt,
        })
        rec['total'] += amt

    high_avg_total = sum(item['amount'] for item in high_avg_items)

    # ---- 5. TEAM AWARDS ----
    remainder = (config.total_available
                 - tournament_total
                 - individual_total
                 - high_avg_total
                 - config.trophy_cost)

    try:
        award_pcts = json.loads(config.team_award_pcts_json)
    except (ValueError, TypeError):
        award_pcts = [40, 40, 20]

    try:
        place_pcts_all = json.loads(config.team_place_pcts_json)
    except (ValueError, TypeError):
        place_pcts_all = [[35, 25, 20, 20], [35, 25, 20, 20], [60, 40]]

    champ_start = (config.championship_start_week
                   if config.championship_start_week else 20)

    first_half_standings  = get_team_standings(season_id, half=1)
    second_half_standings = get_team_standings(season_id, half=2)

    # Championship: TeamPoints for weeks >= champ_start
    champ_pts_rows = (TeamPoints.query
                      .filter_by(season_id=season_id)
                      .filter(TeamPoints.week_num >= champ_start)
                      .all())
    champ_map = {}
    for tp_row in champ_pts_rows:
        if tp_row.team_id not in champ_map:
            champ_map[tp_row.team_id] = {'team': tp_row.team, 'points': 0}
        champ_map[tp_row.team_id]['points'] += tp_row.points_earned
    champ_standings = sorted(champ_map.values(), key=lambda x: x['points'], reverse=True)

    award_defs = [
        ('First Half',   first_half_standings,  award_pcts[0] if len(award_pcts) > 0 else 40),
        ('Second Half',  second_half_standings, award_pcts[1] if len(award_pcts) > 1 else 40),
        ('Championship', champ_standings,       award_pcts[2] if len(award_pcts) > 2 else 20),
    ]

    # Split the remainder into the three award pools as whole dollars,
    # leftover going to First Half first, then Second, then Championship.
    pool_pcts = [d[2] for d in award_defs]
    pool_amounts = _split_whole_dollars(remainder, pool_pcts)

    # Accumulate per-team totals across all three awards
    team_totals = {}  # team_id -> {team, captain, prizes, total}

    def _get_tt(team):
        tid = team.id
        if tid not in team_totals:
            team_totals[tid] = {
                'team':    team,
                'captain': team.captain_name or '',
                'prizes':  [],
                'total':   0.0,
            }
        return team_totals[tid]

    team_awards = []  # for summary page: [{name, pool_amount, pool_pct, rows}]
    for (award_def, place_pcts, pool_amount) in zip(award_defs, place_pcts_all, pool_amounts):
        award_name, standings, pool_pct = award_def
        # Only as many place buckets as there are standings, and only positive pcts.
        effective_pcts = [(i, place_pcts[i] if i < len(place_pcts) else 0)
                          for i in range(len(standings))]
        effective_pcts = [(i, p) for i, p in effective_pcts if p > 0]
        active_pcts = [p for _, p in effective_pcts]
        # Split the pool into whole-dollar place amounts; leftover to top rank.
        place_amounts = _split_whole_dollars(pool_amount, active_pcts)

        award_rows = []
        for (i, _pct), amount in zip(effective_pcts, place_amounts):
            if amount <= 0:
                continue
            standing = standings[i]
            place_label = PLACE_LABELS[i] if i < len(PLACE_LABELS) else f'{i+1}th'
            tt = _get_tt(standing['team'])
            tt['prizes'].append({
                'type':   'team_finish',
                'label':  f"{award_name} \u2014 {place_label} Place",
                'detail': f"{standing['points']} pts",
                'amount': amount,
            })
            tt['total'] += amount
            award_rows.append({
                'team':   standing['team'],
                'place':  place_label,
                'points': standing['points'],
                'amount': amount,
            })
        team_awards.append({
            'name':        award_name,
            'pool_amount': pool_amount,
            'pool_pct':    pool_pct,
            'rows':        award_rows,
        })

    team_payouts = sorted(team_totals.values(), key=lambda x: x['team'].number)
    team_total = sum(tt['total'] for tt in team_payouts)

    # Sort individual payouts alphabetically
    individual_payouts = sorted(ind_map.values(),
                                key=lambda x: x['bowler'].last_name)

    return {
        'total_available':    config.total_available,
        'tournament_items':   tournament_items,
        'tournament_total':   tournament_total,
        'high_avg_items':     high_avg_items,
        'high_avg_total':     high_avg_total,
        'individual_payouts': individual_payouts,
        'individual_total':   individual_total,
        'trophy_cost':        config.trophy_cost,
        'team_awards':        team_awards,
        'team_payouts':       team_payouts,
        'team_total':         team_total,
        'remainder':          remainder,
        'final_week':         final_week,
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
            'team_label': team.name if team else '',
            'prizes':      ind['prizes'],
            'total':      ind['total'],
        })

    # Tournament winners who are guests (no bowler record)
    guest_tourney = [t for t in payout['tournament_items'] if t['bowler'] is None]
    # (guests don't get individual award pages since they have no bowler record)

    # Team recipients
    for tt in payout['team_payouts']:
        team = tt['team']
        display_name = team.name
        recipients.append({
            'type':    'team',
            'team':    team,
            'name':    display_name,
            'captain': tt['captain'],
            'prizes':  tt['prizes'],
            'total':   tt['total'],
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
        config.high_avg_prize_1   = float(request.form.get('high_avg_prize_1', 125))
        config.high_avg_prize_2   = float(request.form.get('high_avg_prize_2', 100))
        config.high_avg_prize_3   = float(request.form.get('high_avg_prize_3', 75))
        config.weekly_win_rate    = float(request.form.get('weekly_win_rate', 10))
        config.ytd_prize_rate     = float(request.form.get('ytd_prize_rate', 75))
        config.trophy_cost        = float(request.form.get('trophy_cost', 125))
        config.final_week         = int(request.form.get('final_week', 22))

        try:
            award_pcts = [float(request.form.get(f'award_pct_{i}', 0)) for i in range(3)]
            config.team_award_pcts_json = json.dumps(award_pcts)
        except ValueError:
            flash('Award pool percentages must be numbers.', 'warning')
            return redirect(url_for('payout.payout_config', season_id=season_id))

        try:
            place_pcts_all = []
            for i in range(3):
                raw = request.form.get(f'place_pcts_{i}', '')
                pcts = [float(x.strip()) for x in raw.split(',') if x.strip()]
                place_pcts_all.append(pcts)
            config.team_place_pcts_json = json.dumps(place_pcts_all)
        except ValueError:
            flash('Place percentages must be comma-separated numbers.', 'warning')
            return redirect(url_for('payout.payout_config', season_id=season_id))

        try:
            config.championship_start_week = int(request.form.get('championship_start_week', 20))
        except ValueError:
            config.championship_start_week = 20

        db.session.commit()
        return redirect(url_for('payout.payout_summary', season_id=season_id))

    try:
        award_pcts = json.loads(config.team_award_pcts_json)
    except (ValueError, TypeError):
        award_pcts = [40, 40, 20]

    try:
        place_pcts_all = json.loads(config.team_place_pcts_json)
    except (ValueError, TypeError):
        place_pcts_all = [[35, 25, 20, 20], [35, 25, 20, 20], [60, 40]]

    place_pcts_strs = [
        ', '.join(str(int(x)) for x in lst) for lst in place_pcts_all
    ]

    return render_template('payout/config.html',
                           season=season,
                           config=config,
                           award_pcts=award_pcts,
                           place_pcts_strs=place_pcts_strs)


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
    for tt in payout['team_payouts']:
        team_breakdowns[tt['team'].id] = _currency_breakdown(tt['total'])

    # Tournament guests only — rostered tournament winners are folded into
    # ind['total'] (and therefore into `breakdowns` above), so they must not
    # appear here or the bank inventory would double-count.
    tourney_breakdowns = {}
    for idx, item in enumerate(payout['tournament_items']):
        if item['bowler'] is None:
            tourney_breakdowns[idx] = _currency_breakdown(item['amount'])

    # Aggregate bank inventory (all payees combined)
    agg = {d: 0 for d in [100, 50, 20, 10, 5, 1]}
    for bd in list(breakdowns.values()) + list(team_breakdowns.values()) + list(tourney_breakdowns.values()):
        for d, cnt in bd.items():
            agg[d] += cnt

    # Grand total of cash going out (excludes trophies). Computed from the
    # whole-dollar amounts that drive the bill breakdown, so sum(agg[d]*d)
    # reconciles exactly to grand_total regardless of cents in team awards.
    grand_total = sum(agg[d] * d for d in agg)

    return render_template('payout/summary.html',
                           season=season,
                           payout=payout,
                           breakdowns=breakdowns,
                           team_breakdowns=team_breakdowns,
                           tourney_breakdowns=tourney_breakdowns,
                           agg=agg,
                           grand_total=grand_total,
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

"""
Mobile PWA routes — /m/
Serves a phone-optimised view of standings, scores, lane assignments, and bowler stats.
Device detection lives in app.py (before_request). Preference toggle handled here.
"""
import json
import os
from datetime import date, timedelta

from flask import Blueprint, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from models import Bowler, MatchupEntry, PushSubscription, Roster, ScheduleEntry, Season, Team, TeamPoints, TournamentEntry, Week, db
from calculations import calculate_handicap, get_team_standings, get_bowler_stats

mobile_bp = Blueprint('mobile', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_season():
    return Season.query.filter_by(is_active=True).first()


def _my_roster(season):
    if not season or not current_user.is_authenticated:
        return None
    return Roster.query.filter_by(
        bowler_id=current_user.id,
        season_id=season.id,
    ).first()


def _team_totals(season_id):
    """Return {team_id: total_points} for the given season."""
    rows = (db.session.query(TeamPoints.team_id, func.sum(TeamPoints.points_earned))
            .filter_by(season_id=season_id)
            .group_by(TeamPoints.team_id)
            .all())
    return {tid: float(pts) for tid, pts in rows}


# ---------------------------------------------------------------------------
# Preference toggles
# ---------------------------------------------------------------------------

@mobile_bp.route('/prefer-desktop')
def prefer_desktop():
    dest = request.args.get('next') or '/'
    resp = make_response(redirect(dest))
    resp.set_cookie('prefer_desktop', '1', max_age=60 * 60 * 24 * 365, samesite='Lax')
    return resp


@mobile_bp.route('/prefer-mobile')
def prefer_mobile():
    resp = make_response(redirect(url_for('mobile.home')))
    resp.delete_cookie('prefer_desktop')
    return resp


# ---------------------------------------------------------------------------
# Push notification endpoints
# ---------------------------------------------------------------------------

@mobile_bp.route('/push/vapid-public-key')
def push_vapid_key():
    """Return the VAPID public key so the browser can subscribe."""
    return jsonify({'publicKey': os.getenv('VAPID_PUBLIC_KEY', '')})


@mobile_bp.route('/push/subscribe', methods=['POST'])
@login_required
def push_subscribe():
    """Store or update a push subscription for the current user."""
    data = request.get_json(force=True)
    sub_data = data.get('subscription', {})
    endpoint = sub_data.get('endpoint', '')
    platform = data.get('platform', 'unknown')

    if not endpoint:
        return jsonify({'error': 'missing endpoint'}), 400

    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if sub:
        # Update ownership and subscription JSON in case keys rotated
        sub.bowler_id = current_user.id
        sub.subscription_json = json.dumps(sub_data)
        sub.platform = platform
    else:
        sub = PushSubscription(
            bowler_id=current_user.id,
            endpoint=endpoint,
            subscription_json=json.dumps(sub_data),
            platform=platform,
        )
        db.session.add(sub)
    db.session.commit()
    return jsonify({'ok': True}), 201


@mobile_bp.route('/push/unsubscribe', methods=['POST'])
@login_required
def push_unsubscribe():
    """Remove a push subscription (user turned off notifications in browser)."""
    data = request.get_json(force=True)
    endpoint = (data.get('subscription') or {}).get('endpoint', '')
    if endpoint:
        PushSubscription.query.filter_by(
            endpoint=endpoint, bowler_id=current_user.id
        ).delete()
        db.session.commit()
    return jsonify({'ok': True})


@mobile_bp.route('/push/preferences', methods=['POST'])
@login_required
def push_preferences():
    """Update notification preference toggles for all of the current user's subscriptions."""
    subs = PushSubscription.query.filter_by(bowler_id=current_user.id).all()
    if not subs:
        return redirect(url_for('mobile.me'))
    tomorrow = 'pref_bowling_tomorrow' in request.form
    tonight = 'pref_bowling_tonight' in request.form
    scores = 'pref_scores_posted' in request.form
    for sub in subs:
        sub.pref_bowling_tomorrow = tomorrow
        sub.pref_bowling_tonight = tonight
        sub.pref_scores_posted = scores
    db.session.commit()
    return redirect(url_for('mobile.me'))


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@mobile_bp.route('/')
@login_required
def home():
    season = _active_season()
    roster = _my_roster(season)
    my_team = roster.team if roster else None

    upcoming_week = None
    all_matchups = []       # list of ScheduleEntry for upcoming week
    my_matchup = None       # the user's own ScheduleEntry
    games_played = 0        # user's regular-season games (for tournament eligibility)
    last_week = None
    last_week_type = None
    last_week_pts = None
    last_week_opp_pts = None
    last_week_opp = None
    last_week_champ = []
    last_week_top3 = []

    _SOLO_TYPES = {'indiv_scratch', 'indiv_hcp_1', 'indiv_hcp_2'}

    if season:
        # Last entered week (any type)
        last_week = (Week.query
                     .filter_by(season_id=season.id, is_entered=True)
                     .order_by(Week.week_num.desc())
                     .first())

        # Next unentered, uncancelled week of ANY type
        upcoming_week = (Week.query
                         .filter_by(season_id=season.id, is_entered=False, is_cancelled=False)
                         .order_by(Week.week_num)
                         .first())

        if upcoming_week:
            # All lane assignments for the upcoming week (regular, position night, championship)
            all_matchups = (ScheduleEntry.query
                            .filter_by(season_id=season.id, week_num=upcoming_week.week_num)
                            .order_by(ScheduleEntry.matchup_num)
                            .all())
            if my_team:
                my_matchup = next(
                    (m for m in all_matchups
                     if m.team1_id == my_team.id or m.team2_id == my_team.id),
                    None
                )

        # Games played in regular season (for tournament eligibility display)
        regular_entries = (MatchupEntry.query
                           .filter_by(season_id=season.id, bowler_id=current_user.id, is_blind=False)
                           .filter(MatchupEntry.week_num <= season.num_weeks)
                           .all())
        for e in regular_entries:
            games_played += len(e.games_night1)

        # Roster with handicaps — all active bowlers grouped by team for the home screen
        roster_by_team = []
        next_week_num = upcoming_week.week_num if upcoming_week else season.num_weeks + 1
        for team in Team.query.filter_by(season_id=season.id).order_by(Team.number).all():
            rosters = (Roster.query
                       .filter_by(season_id=season.id, team_id=team.id, active=True)
                       .join(Bowler, Bowler.id == Roster.bowler_id)
                       .order_by(Bowler.last_name, Bowler.first_name)
                       .all())
            bowler_rows = []
            for r in rosters:
                hcp = calculate_handicap(r.bowler_id, season.id, next_week_num)
                bowler_rows.append({
                    'first_name': r.bowler.first_name,
                    'last_name': r.bowler.last_name,
                    'nickname': r.bowler.nickname,
                    'handicap': hcp,
                })
            roster_by_team.append({'team': team, 'bowlers': bowler_rows})

        if last_week:
            tt = last_week.tournament_type
            if tt == 'club_championship':
                last_week_type = 'championship'
                wk_pts = TeamPoints.query.filter_by(
                    season_id=season.id, week_num=last_week.week_num
                ).all()
                totals = {}
                for p in wk_pts:
                    totals[p.team_id] = totals.get(p.team_id, 0) + p.points_earned
                champ_teams = Team.query.filter(Team.id.in_(totals.keys())).all()
                last_week_champ = sorted(
                    [{'team': t, 'pts': totals[t.id]} for t in champ_teams],
                    key=lambda x: -x['pts']
                )
            elif tt in _SOLO_TYPES:
                last_week_type = 'solo'
                entries = TournamentEntry.query.filter_by(
                    season_id=season.id, week_num=last_week.week_num
                ).all()
                use_hcp = tt in ('indiv_hcp_1', 'indiv_hcp_2')
                entries_with_score = [
                    (e.total_with_hcp if use_hcp else e.total_scratch, e)
                    for e in entries if e.games
                ]
                entries_with_score.sort(key=lambda x: -x[0])
                last_week_top3 = [
                    {'name': e.display_name, 'score': score}
                    for score, e in entries_with_score[:3]
                ]
            else:
                last_week_type = 'regular'
                if my_team:
                    week_pts = TeamPoints.query.filter_by(
                        season_id=season.id, week_num=last_week.week_num
                    ).all()
                    totals = {}
                    for p in week_pts:
                        totals[p.team_id] = totals.get(p.team_id, 0) + p.points_earned
                    last_week_pts = totals.get(my_team.id)
                    last_matchup = (ScheduleEntry.query
                                    .filter_by(season_id=season.id, week_num=last_week.week_num)
                                    .filter(db.or_(ScheduleEntry.team1_id == my_team.id,
                                                   ScheduleEntry.team2_id == my_team.id))
                                    .first())
                    if last_matchup:
                        last_week_opp = (last_matchup.team2
                                         if last_matchup.team1_id == my_team.id
                                         else last_matchup.team1)
                        last_week_opp_pts = totals.get(last_week_opp.id) if last_week_opp else None

    # Harry Russell qualifiers: top-10 avg bowlers with ≥30 regular-season games
    hr_qualifiers = []
    if season and upcoming_week and upcoming_week.tournament_type == 'indiv_scratch':
        last_regular = (Week.query
                        .filter_by(season_id=season.id)
                        .filter(Week.tournament_type.is_(None))
                        .order_by(Week.week_num.desc())
                        .first())
        through = last_regular.week_num if last_regular else upcoming_week.week_num - 1
        rostered = (Roster.query
                    .filter_by(season_id=season.id)
                    .join(Bowler, Bowler.id == Roster.bowler_id)
                    .order_by(Bowler.last_name)
                    .all())
        qual_list = []
        for r in rostered:
            stats = get_bowler_stats(r.bowler_id, season.id, through)
            if stats['cumulative_games'] >= 30:
                qual_list.append((stats['current_average'], r.bowler))
        qual_list.sort(key=lambda x: -x[0])
        if qual_list:
            top10_avgs = set(sorted({avg for avg, _ in qual_list}, reverse=True)[:10])
            qual_list = [(avg, b) for avg, b in qual_list if avg in top10_avgs]
        for _, b in qual_list:
            first_init = b.first_name[0] + '.' if b.first_name else ''
            nick = f' ({b.nickname})' if b.nickname else ''
            hr_qualifiers.append(f'{first_init} {b.last_name}{nick}'.strip())

    return render_template('mobile/home.html',
                           season=season,
                           my_team=my_team,
                           upcoming_week=upcoming_week,
                           all_matchups=all_matchups,
                           my_matchup=my_matchup,
                           games_played=games_played,
                           hr_qualifiers=hr_qualifiers,
                           last_week=last_week,
                           last_week_type=last_week_type,
                           last_week_pts=last_week_pts,
                           last_week_opp_pts=last_week_opp_pts,
                           last_week_opp=last_week_opp,
                           last_week_champ=last_week_champ,
                           last_week_top3=last_week_top3,
                           roster_by_team=roster_by_team)


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

@mobile_bp.route('/standings')
@login_required
def standings():
    season = _active_season()
    teams = []
    fh_map = {}
    sh_map = {}
    if season:
        overall = get_team_standings(season.id)
        fh_list = get_team_standings(season.id, half=1)
        sh_list = get_team_standings(season.id, half=2)
        fh_map = {r['team'].id: r['points'] for r in fh_list}
        sh_map = {r['team'].id: r['points'] for r in sh_list}
        teams = [
            {
                'team': r['team'],
                'points': r['points'],
                'fh': fh_map.get(r['team'].id, 0),
                'sh': sh_map.get(r['team'].id, 0),
            }
            for r in overall
        ]
    return render_template('mobile/standings.html', season=season, teams=teams)


# ---------------------------------------------------------------------------
# Scores — week list then week detail
# ---------------------------------------------------------------------------

@mobile_bp.route('/scores')
@login_required
def scores():
    season = _active_season()
    entered_weeks = []
    if season:
        entered_weeks = (Week.query
                         .filter_by(season_id=season.id, is_entered=True)
                         .filter(Week.week_num <= season.num_weeks + 4)
                         .order_by(Week.week_num.desc())
                         .all())
    return render_template('mobile/scores.html', season=season, weeks=entered_weeks)


@mobile_bp.route('/scores/week/<int:week_num>')
@login_required
def week_scores(week_num):
    season = _active_season()
    if not season:
        return redirect(url_for('mobile.scores'))

    week = Week.query.filter_by(season_id=season.id, week_num=week_num).first_or_404()
    entries = (MatchupEntry.query
               .filter_by(season_id=season.id, week_num=week_num)
               .filter(MatchupEntry.is_blind == False)
               .filter(MatchupEntry.bowler_id != None)
               .order_by(MatchupEntry.team_id, MatchupEntry.matchup_num)
               .all())

    # Group by team
    teams_dict = {}
    for e in entries:
        if e.team_id not in teams_dict:
            teams_dict[e.team_id] = {'team': e.team, 'entries': []}
        teams_dict[e.team_id]['entries'].append(e)
    team_groups = sorted(teams_dict.values(), key=lambda x: x['team'].number)

    return render_template('mobile/week_scores.html',
                           season=season, week=week, team_groups=team_groups)


# ---------------------------------------------------------------------------
# Me — personal stats
# ---------------------------------------------------------------------------

@mobile_bp.route('/me')
@login_required
def me():
    season = _active_season()
    roster = _my_roster(season)

    entries = []
    avg = None
    hg_scratch = None
    hs_scratch = None

    prior_seasons = []

    if season:
        entries = (MatchupEntry.query
                   .filter_by(season_id=season.id, bowler_id=current_user.id)
                   .order_by(MatchupEntry.week_num)
                   .all())

        all_games = []
        for e in entries:
            all_games.extend(e.games_night1)

        if all_games:
            avg = round(sum(all_games) / len(all_games), 1)
            hg_scratch = max(all_games)

        # High series: best 3-game total per week
        week_series = {}
        for e in entries:
            g = e.games_night1
            if len(g) == 3:
                week_series[e.week_num] = max(
                    week_series.get(e.week_num, 0), sum(g)
                )
        if week_series:
            hs_scratch = max(week_series.values())

    # If no current-season scores, build a per-season history from prior years
    has_current_scores = any(e.games_night1 for e in entries)
    if not has_current_scores:
        prior_entries = (MatchupEntry.query
                         .filter_by(bowler_id=current_user.id, is_blind=False)
                         .filter(MatchupEntry.game1 != None)
                         .all())
        season_buckets = {}
        current_sid = season.id if season else None
        for e in prior_entries:
            if e.season_id == current_sid:
                continue
            season_buckets.setdefault(e.season_id, []).append(e)

        if season_buckets:
            all_season_ids = list(season_buckets.keys())
            seasons_map = {s.id: s for s in
                           Season.query.filter(Season.id.in_(all_season_ids)).all()}
            for sid in sorted(all_season_ids,
                              key=lambda x: seasons_map[x].name if x in seasons_map else '',
                              reverse=True):
                ses_entries = season_buckets[sid]
                games = []
                for e in ses_entries:
                    games.extend(e.games_night1)
                if not games:
                    continue
                wk_series = {}
                for e in ses_entries:
                    g = e.games_night1
                    if len(g) == 3:
                        wk_series[e.week_num] = max(wk_series.get(e.week_num, 0), sum(g))
                prior_seasons.append({
                    'season': seasons_map.get(sid),
                    'games': len(games),
                    'avg': round(sum(games) / len(games), 1),
                    'hg': max(games),
                    'hs': max(wk_series.values()) if wk_series else None,
                })

    # Push notification state
    push_subs = PushSubscription.query.filter_by(bowler_id=current_user.id).all()
    push_prefs = push_subs[0] if push_subs else None
    vapid_public_key = os.getenv('VAPID_PUBLIC_KEY', '')

    return render_template('mobile/me.html',
                           season=season,
                           roster=roster,
                           entries=entries,
                           avg=avg,
                           hg_scratch=hg_scratch,
                           hs_scratch=hs_scratch,
                           prior_seasons=prior_seasons,
                           push_subs=push_subs,
                           push_prefs=push_prefs,
                           vapid_public_key=vapid_public_key)


# ---------------------------------------------------------------------------
# Schedule — full season calendar with break detection
# ---------------------------------------------------------------------------

@mobile_bp.route('/schedule')
@login_required
def schedule():
    season = _active_season()
    show_all = request.args.get('show_all') == '1'
    schedule_rows = []   # list of dicts: {date, week, is_break, matchups}

    if season:
        weeks = (Week.query
                 .filter_by(season_id=season.id)
                 .order_by(Week.week_num)
                 .all())

        # Pre-load all schedule entries so we can show matchups per week
        all_sched = (ScheduleEntry.query
                     .filter_by(season_id=season.id)
                     .order_by(ScheduleEntry.week_num, ScheduleEntry.matchup_num)
                     .all())
        matchups_by_week = {}
        for entry in all_sched:
            matchups_by_week.setdefault(entry.week_num, []).append(entry)

        dated_weeks = [w for w in weeks if w.date]

        if dated_weeks:
            date_to_week = {w.date: w for w in dated_weeks}
            first_date = dated_weeks[0].date
            last_date = dated_weeks[-1].date

            current = first_date
            while current <= last_date:
                if current in date_to_week:
                    wk = date_to_week[current]
                    schedule_rows.append({
                        'date': current,
                        'week': wk,
                        'is_break': False,
                        'matchups': matchups_by_week.get(wk.week_num, []),
                    })
                else:
                    schedule_rows.append({
                        'date': current,
                        'week': None,
                        'is_break': True,
                        'matchups': [],
                    })
                current += timedelta(weeks=1)
        else:
            # No dates set yet — show weeks without dates
            for w in weeks:
                schedule_rows.append({
                    'date': None,
                    'week': w,
                    'is_break': False,
                    'matchups': matchups_by_week.get(w.week_num, []),
                })

    if not show_all:
        schedule_rows = [r for r in schedule_rows
                         if not r['is_break']
                         and not r['week'].is_entered
                         and not r['week'].is_cancelled]

    return render_template('mobile/schedule.html', season=season,
                           schedule_rows=schedule_rows, show_all=show_all)

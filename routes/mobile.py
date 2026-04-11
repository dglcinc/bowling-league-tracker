"""
Mobile PWA routes — /m/
Serves a phone-optimised view of standings, scores, lane assignments, and bowler stats.
Device detection lives in app.py (before_request). Preference toggle handled here.
"""
from datetime import date, timedelta

from flask import Blueprint, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from models import MatchupEntry, Roster, ScheduleEntry, Season, Team, TeamPoints, Week, db

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
    last_week_pts = None
    last_week_opp_pts = None

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

        if my_team and last_week:
            week_pts = (TeamPoints.query
                        .filter_by(season_id=season.id, week_num=last_week.week_num)
                        .all())
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
                last_opp = (last_matchup.team2
                            if last_matchup.team1_id == my_team.id
                            else last_matchup.team1)
                last_week_opp_pts = totals.get(last_opp.id)

    return render_template('mobile/home.html',
                           season=season,
                           my_team=my_team,
                           upcoming_week=upcoming_week,
                           all_matchups=all_matchups,
                           my_matchup=my_matchup,
                           games_played=games_played,
                           last_week=last_week,
                           last_week_pts=last_week_pts,
                           last_week_opp_pts=last_week_opp_pts)


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

@mobile_bp.route('/standings')
@login_required
def standings():
    season = _active_season()
    teams = []
    if season:
        totals = _team_totals(season.id)
        all_teams = Team.query.filter_by(season_id=season.id).order_by(Team.number).all()
        teams = sorted(
            [{'team': t, 'points': totals.get(t.id, 0)} for t in all_teams],
            key=lambda x: x['points'],
            reverse=True,
        )
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

    return render_template('mobile/me.html',
                           season=season,
                           roster=roster,
                           entries=entries,
                           avg=avg,
                           hg_scratch=hg_scratch,
                           hs_scratch=hs_scratch)


# ---------------------------------------------------------------------------
# Schedule — full season calendar with break detection
# ---------------------------------------------------------------------------

@mobile_bp.route('/schedule')
@login_required
def schedule():
    season = _active_season()
    schedule_rows = []   # list of dicts: {date, week, is_break}

    if season:
        weeks = (Week.query
                 .filter_by(season_id=season.id)
                 .order_by(Week.week_num)
                 .all())

        dated_weeks = [w for w in weeks if w.date]

        if dated_weeks:
            date_to_week = {w.date: w for w in dated_weeks}
            first_date = dated_weeks[0].date
            last_date = dated_weeks[-1].date

            current = first_date
            while current <= last_date:
                if current in date_to_week:
                    schedule_rows.append({
                        'date': current,
                        'week': date_to_week[current],
                        'is_break': False,
                    })
                else:
                    schedule_rows.append({
                        'date': current,
                        'week': None,
                        'is_break': True,
                    })
                current += timedelta(weeks=1)
        else:
            # No dates set yet — show weeks without dates
            for w in weeks:
                schedule_rows.append({'date': None, 'week': w, 'is_break': False})

    return render_template('mobile/schedule.html', season=season, schedule_rows=schedule_rows)

"""
Admin routes: season setup, roster management, schedule entry, season rollover.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Season, Team, Roster, Bowler, Week, ScheduleEntry, MatchupEntry
from datetime import date, timedelta

admin_bp = Blueprint('admin', __name__)


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------

@admin_bp.route('/seasons')
def seasons():
    all_seasons = Season.query.order_by(Season.name.desc()).all()
    return render_template('admin/seasons.html', seasons=all_seasons)


@admin_bp.route('/seasons/new', methods=['GET', 'POST'])
def new_season():
    if request.method == 'POST':
        name = request.form['name'].strip()
        start_date_str = request.form.get('start_date')
        num_weeks = int(request.form.get('num_weeks', 23))
        half_boundary = int(request.form.get('half_boundary_week', 11))

        if Season.query.filter_by(name=name).first():
            flash(f'Season "{name}" already exists.', 'danger')
            return redirect(url_for('admin.new_season'))

        # Deactivate current active season
        Season.query.filter_by(is_active=True).update({'is_active': False})

        season = Season(
            name=name,
            num_weeks=num_weeks,
            half_boundary_week=half_boundary,
            is_active=True,
        )
        if start_date_str:
            season.start_date = date.fromisoformat(start_date_str)

        db.session.add(season)
        db.session.flush()  # get season.id

        # Create 4 default teams
        default_teams = ['Lewis', 'Ferrante', 'Belyea', 'Mancini']
        for i, tname in enumerate(default_teams, 1):
            team = Team(season_id=season.id, number=i, name=tname)
            db.session.add(team)

        # Create week records
        for wn in range(1, num_weeks + 1):
            wk = Week(
                season_id=season.id,
                week_num=wn,
                is_position_night=(wn in [half_boundary, num_weeks - 1]),
            )
            if season.start_date:
                wk.date = season.start_date + timedelta(weeks=wn - 1)
            db.session.add(wk)

        db.session.commit()
        flash(f'Season "{name}" created. Add your roster and schedule next.', 'success')
        return redirect(url_for('admin.season_detail', season_id=season.id))

    return render_template('admin/new_season.html')


@admin_bp.route('/seasons/<int:season_id>')
def season_detail(season_id):
    season = Season.query.get_or_404(season_id)
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.number).all()
    roster = (Roster.query
              .filter_by(season_id=season_id)
              .join(Bowler)
              .order_by(Bowler.last_name)
              .all())
    return render_template('admin/season_detail.html',
                           season=season, teams=teams, roster=roster)


# ---------------------------------------------------------------------------
# Roster management
# ---------------------------------------------------------------------------

@admin_bp.route('/seasons/<int:season_id>/roster/add', methods=['GET', 'POST'])
def add_bowler(season_id):
    season = Season.query.get_or_404(season_id)
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.number).all()
    # Bowlers not already on this season's roster
    existing_ids = [r.bowler_id for r in Roster.query.filter_by(season_id=season_id)]
    available = Bowler.query.filter(
        Bowler.id.notin_(existing_ids)
    ).order_by(Bowler.last_name).all() if existing_ids else Bowler.query.order_by(Bowler.last_name).all()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'existing':
            bowler_id = int(request.form['bowler_id'])
        else:
            # Create new bowler
            bowler = Bowler(
                last_name=request.form['last_name'].strip(),
                first_name=request.form.get('first_name', '').strip() or None,
                nickname=request.form.get('nickname', '').strip() or None,
                email=request.form.get('email', '').strip() or None,
            )
            db.session.add(bowler)
            db.session.flush()
            bowler_id = bowler.id

        team_id = int(request.form['team_id'])
        prior_hcp = int(request.form.get('prior_handicap') or 0)
        joined_week = int(request.form.get('joined_week') or 1)

        roster_entry = Roster(
            bowler_id=bowler_id,
            season_id=season_id,
            team_id=team_id,
            active=True,
            prior_handicap=prior_hcp,
            joined_week=joined_week,
        )
        db.session.add(roster_entry)
        db.session.commit()
        flash('Bowler added to roster.', 'success')
        return redirect(url_for('admin.season_detail', season_id=season_id))

    return render_template('admin/add_bowler.html',
                           season=season, teams=teams, available=available)


@admin_bp.route('/seasons/<int:season_id>/roster/<int:roster_id>/toggle', methods=['POST'])
def toggle_active(season_id, roster_id):
    r = Roster.query.get_or_404(roster_id)
    r.active = not r.active
    db.session.commit()
    return redirect(url_for('admin.season_detail', season_id=season_id))


@admin_bp.route('/seasons/<int:season_id>/roster/<int:roster_id>/edit', methods=['GET', 'POST'])
def edit_roster(season_id, roster_id):
    r = Roster.query.get_or_404(roster_id)
    season = Season.query.get_or_404(season_id)
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.number).all()

    if request.method == 'POST':
        r.team_id = int(request.form['team_id'])
        r.prior_handicap = int(request.form.get('prior_handicap') or 0)
        r.joined_week = int(request.form.get('joined_week') or 1)
        db.session.commit()
        flash('Roster entry updated.', 'success')
        return redirect(url_for('admin.season_detail', season_id=season_id))

    return render_template('admin/edit_roster.html', r=r, season=season, teams=teams)


# ---------------------------------------------------------------------------
# Schedule management
# ---------------------------------------------------------------------------

@admin_bp.route('/seasons/<int:season_id>/schedule', methods=['GET', 'POST'])
def schedule(season_id):
    season = Season.query.get_or_404(season_id)
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.number).all()
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()
    existing = ScheduleEntry.query.filter_by(season_id=season_id).all()

    # Build lookup: {(week_num, matchup_num): entry}
    sched_map = {(e.week_num, e.matchup_num): e for e in existing}

    return render_template('admin/schedule.html',
                           season=season, teams=teams,
                           weeks=weeks, sched_map=sched_map)


@admin_bp.route('/seasons/<int:season_id>/schedule/save', methods=['POST'])
def save_schedule(season_id):
    """Save schedule entries from form. Expects fields like week_1_matchup_1_t1, etc."""
    season = Season.query.get_or_404(season_id)

    for key, val in request.form.items():
        # Expected key format: week_{wn}_matchup_{mn}_{field}
        # field = t1 (team1_id), t2 (team2_id), lane
        parts = key.split('_')
        if len(parts) < 5 or parts[0] != 'week' or parts[2] != 'matchup':
            continue
        try:
            wn = int(parts[1])
            mn = int(parts[3])
            field = parts[4]
        except (ValueError, IndexError):
            continue

        entry = ScheduleEntry.query.filter_by(
            season_id=season_id, week_num=wn, matchup_num=mn
        ).first()
        if not entry:
            entry = ScheduleEntry(season_id=season_id, week_num=wn, matchup_num=mn)
            db.session.add(entry)

        if field == 't1' and val:
            entry.team1_id = int(val)
        elif field == 't2' and val:
            entry.team2_id = int(val)
        elif field == 'lane' and val:
            entry.lane_pair = val.strip()

    db.session.commit()
    flash('Schedule saved.', 'success')
    return redirect(url_for('admin.schedule', season_id=season_id))


# ---------------------------------------------------------------------------
# Week date editing
# ---------------------------------------------------------------------------

@admin_bp.route('/seasons/<int:season_id>/weeks', methods=['GET', 'POST'])
def edit_weeks(season_id):
    season = Season.query.get_or_404(season_id)
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()

    if request.method == 'POST':
        for wk in weeks:
            date_str = request.form.get(f'date_{wk.week_num}')
            pos_night = request.form.get(f'pos_{wk.week_num}') == 'on'
            if date_str:
                wk.date = date.fromisoformat(date_str)
            wk.is_position_night = pos_night
        db.session.commit()
        flash('Week dates saved.', 'success')
        return redirect(url_for('admin.season_detail', season_id=season_id))

    return render_template('admin/edit_weeks.html', season=season, weeks=weeks)


# ---------------------------------------------------------------------------
# Matchup assignment (historical data fix)
# ---------------------------------------------------------------------------

@admin_bp.route('/seasons/<int:season_id>/assign_matchups')
def assign_matchups_list(season_id):
    season = Season.query.get_or_404(season_id)
    weeks = (Week.query
             .filter_by(season_id=season_id, is_entered=True, is_cancelled=False)
             .order_by(Week.week_num)
             .all())
    return render_template('admin/assign_matchups_list.html', season=season, weeks=weeks)


@admin_bp.route('/seasons/<int:season_id>/assign_matchups/<int:week_num>',
                methods=['GET', 'POST'])
def assign_matchups(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()

    schedules = (ScheduleEntry.query
                 .filter_by(season_id=season_id, week_num=week_num)
                 .order_by(ScheduleEntry.matchup_num)
                 .all())

    # Build pairings: matchups 1&2 → pairing A, matchups 3&4 → pairing B
    pairings = []
    for base in [1, 3]:
        s1 = next((s for s in schedules if s.matchup_num == base), None)
        s2 = next((s for s in schedules if s.matchup_num == base + 1), None)
        if s1:
            pairings.append({'mnum1': base, 'mnum2': base + 1,
                             'sched1': s1, 'sched2': s2,
                             'teams': [s1.team1, s1.team2]})

    if request.method == 'POST':
        for key, val in request.form.items():
            if key.startswith('entry_'):
                entry_id = int(key[6:])
                entry = MatchupEntry.query.get(entry_id)
                if entry:
                    entry.matchup_num = int(val)

        db.session.flush()

        # Remove old blinds, re-add to balance each matchup
        MatchupEntry.query.filter_by(
            season_id=season_id, week_num=week_num, is_blind=True
        ).delete()
        db.session.flush()

        for pairing in pairings:
            for mnum in [pairing['mnum1'], pairing['mnum2']]:
                sched = pairing['sched1'] if mnum == pairing['mnum1'] else pairing['sched2']
                if not sched:
                    continue
                for team, other_team, side in [
                    (sched.team1, sched.team2, 'A'),
                    (sched.team2, sched.team1, 'B'),
                ]:
                    c_self = MatchupEntry.query.filter_by(
                        season_id=season_id, week_num=week_num,
                        matchup_num=mnum, team_id=team.id, is_blind=False
                    ).count()
                    c_other = MatchupEntry.query.filter_by(
                        season_id=season_id, week_num=week_num,
                        matchup_num=mnum, team_id=other_team.id, is_blind=False
                    ).count()
                    for _ in range(max(0, c_other - c_self)):
                        db.session.add(MatchupEntry(
                            season_id=season_id, week_num=week_num,
                            matchup_num=mnum, team_id=team.id,
                            is_blind=True, lane_side=side,
                            game1=season.blind_scratch,
                            game2=season.blind_scratch,
                            game3=season.blind_scratch,
                        ))

        db.session.commit()
        flash(f'Week {week_num} assignments saved.', 'success')

        # Advance to next unentered week
        next_week = (Week.query
                     .filter_by(season_id=season_id, is_entered=True, is_cancelled=False)
                     .filter(Week.week_num > week_num)
                     .order_by(Week.week_num)
                     .first())
        if next_week:
            return redirect(url_for('admin.assign_matchups',
                                    season_id=season_id, week_num=next_week.week_num))
        return redirect(url_for('admin.assign_matchups_list', season_id=season_id))

    # GET — load non-blind entries per team for each pairing
    pairing_data = []
    for pairing in pairings:
        team_entries = {}
        for team in pairing['teams']:
            entries = (MatchupEntry.query
                       .filter_by(season_id=season_id, week_num=week_num,
                                  team_id=team.id, is_blind=False)
                       .join(Bowler, MatchupEntry.bowler_id == Bowler.id)
                       .order_by(Bowler.last_name)
                       .all())
            team_entries[team.id] = entries
        pairing_data.append({**pairing, 'team_entries': team_entries})

    return render_template('admin/assign_matchups.html',
                           season=season, week=week, pairing_data=pairing_data)

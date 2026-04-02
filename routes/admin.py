"""
Admin routes: season setup, roster management, schedule entry, season rollover.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Season, Team, Roster, Bowler, Week, ScheduleEntry, MatchupEntry, LeagueSettings
from datetime import date, timedelta
import io

admin_bp = Blueprint('admin', __name__)

# Post-season tournament weeks added after every regular season
_POSTSEASON_WEEKS = [
    ('club_championship', True),   # Club Team Championship — scored as position night
    ('harry_russell',     False),  # Harry E. Russell Championship
    ('chad_harris',       False),  # Chad Harris Memorial Bowl
    ('shep_belyea',       False),  # Shep Belyea Open
]


def _add_postseason_weeks(season, num_regular_weeks):
    """Append 4 post-season tournament weeks after the regular season."""
    for offset, (tt, is_pos) in enumerate(_POSTSEASON_WEEKS, start=1):
        wn = num_regular_weeks + offset
        wk = Week(
            season_id=season.id,
            week_num=wn,
            tournament_type=tt,
            is_position_night=is_pos,
        )
        if season.start_date:
            wk.date = season.start_date + timedelta(weeks=wn - 1)
        db.session.add(wk)


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

        bowling_format = request.form.get('bowling_format', 'single')

        season = Season(
            name=name,
            num_weeks=num_weeks,
            half_boundary_week=half_boundary,
            is_active=True,
            bowling_format=bowling_format,
        )
        if start_date_str:
            season.start_date = date.fromisoformat(start_date_str)

        db.session.add(season)
        db.session.flush()  # get season.id

        # Create 4 default teams with generic names
        for i in range(1, 5):
            tname = request.form.get(f'team{i}_name', '').strip() or f'Team {i}'
            team = Team(season_id=season.id, number=i, name=tname)
            db.session.add(team)

        # Create regular week records
        for wn in range(1, num_weeks + 1):
            wk = Week(
                season_id=season.id,
                week_num=wn,
                is_position_night=(wn in [half_boundary, num_weeks - 1]),
            )
            if season.start_date:
                wk.date = season.start_date + timedelta(weeks=wn - 1)
            db.session.add(wk)

        # Create 4 post-season tournament weeks
        _add_postseason_weeks(season, num_weeks)

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


@admin_bp.route('/settings', methods=['GET', 'POST'])
def league_settings():
    settings = LeagueSettings.query.get(1)
    if not settings:
        settings = LeagueSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    if request.method == 'POST':
        league_name = request.form.get('league_name', '').strip()
        if league_name:
            settings.league_name = league_name
        settings.use_nickname = (request.form.get('use_nickname') == 'on')
        db.session.commit()
        flash('League settings saved.', 'success')
        return redirect(url_for('admin.league_settings'))
    return render_template('admin/league_settings.html', settings=settings)


@admin_bp.route('/bowlers/<int:bowler_id>/edit', methods=['GET', 'POST'])
def edit_bowler(bowler_id):
    bowler = Bowler.query.get_or_404(bowler_id)
    season_id = request.args.get('season_id', type=int) or request.form.get('season_id', type=int)
    season = Season.query.get(season_id) if season_id else None
    roster = Roster.query.filter_by(bowler_id=bowler_id, season_id=season_id).first() if season_id else None
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.number).all() if season_id else []

    if request.method == 'POST':
        last_name = request.form.get('last_name', '').strip()
        if last_name:
            bowler.last_name = last_name
        bowler.first_name = request.form.get('first_name', '').strip() or None
        bowler.nickname = request.form.get('nickname', '').strip() or None
        bowler.email = request.form.get('email', '').strip() or None
        if roster:
            roster.team_id = int(request.form['team_id'])
            roster.prior_handicap = int(request.form.get('prior_handicap') or 0)
            roster.joined_week = int(request.form.get('joined_week') or 1)
        db.session.commit()
        flash('Bowler updated.', 'success')
        if season_id:
            return redirect(url_for('admin.season_detail', season_id=season_id))
        return redirect(url_for('admin.seasons'))

    return render_template('admin/edit_bowler.html', bowler=bowler,
                           season=season, roster=roster, teams=teams)


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

    # Collect all fields per matchup first so we never add a partial entry to the
    # session — an in-session entry with team2_id=None would violate NOT NULL on the
    # next query's autoflush before we get a chance to set team2_id.
    updates = {}
    for key, val in request.form.items():
        # Expected key format: week_{wn}_matchup_{mn}_{field}
        parts = key.split('_')
        if len(parts) < 5 or parts[0] != 'week' or parts[2] != 'matchup':
            continue
        try:
            wn = int(parts[1])
            mn = int(parts[3])
            field = parts[4]
        except (ValueError, IndexError):
            continue
        updates.setdefault((wn, mn), {})[field] = val

    for (wn, mn), fields in updates.items():
        entry = ScheduleEntry.query.filter_by(
            season_id=season_id, week_num=wn, matchup_num=mn
        ).first()
        if not entry:
            entry = ScheduleEntry(season_id=season_id, week_num=wn, matchup_num=mn)
            db.session.add(entry)

        if fields.get('t1'):
            entry.team1_id = int(fields['t1'])
        if fields.get('t2'):
            entry.team2_id = int(fields['t2'])
        if fields.get('lane'):
            entry.lane_pair = fields['lane'].strip()

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

    TOURNAMENT_TYPES = [
        ('', '— Regular week —'),
        ('club_championship', 'Club Team Championship'),
        ('harry_russell', 'Harry E. Russell Championship'),
        ('chad_harris', 'Chad Harris Memorial Bowl'),
        ('shep_belyea', 'Shep Belyea Open'),
    ]

    if request.method == 'POST':
        for wk in weeks:
            date_str = request.form.get(f'date_{wk.week_num}')
            pos_night = request.form.get(f'pos_{wk.week_num}') == 'on'
            tournament_type = request.form.get(f'tournament_{wk.week_num}') or None
            if date_str:
                wk.date = date.fromisoformat(date_str)
            wk.is_position_night = pos_night
            wk.tournament_type = tournament_type
        db.session.commit()
        flash('Week dates saved.', 'success')
        return redirect(url_for('admin.season_detail', season_id=season_id))

    return render_template('admin/edit_weeks.html', season=season, weeks=weeks,
                           tournament_types=TOURNAMENT_TYPES)


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


# ---------------------------------------------------------------------------
# XLS season import (web UI)
# ---------------------------------------------------------------------------

NON_BOWLER_SHEETS = {
    'Instructions', 'Parameters', '2025 Banquet', 'wkly alpha', 'YTD alpha',
    'wkly high average', 'High Games ', 'team scoring', 'dummy', 'blinds',
    'Payout Formula', 'indiv payout', 'final handicap',
}

SKIP_NAMES = {'6 games worksheet', 'weekly highs'}


@admin_bp.route('/import_season', methods=['GET', 'POST'])
def import_season():
    if request.method == 'POST':
        try:
            import openpyxl
        except ImportError:
            flash('openpyxl is not installed. Run: pip install openpyxl', 'danger')
            return redirect(url_for('admin.import_season'))

        f = request.files.get('xls_file')
        if not f or not f.filename:
            flash('No file selected.', 'danger')
            return redirect(url_for('admin.import_season'))

        season_name = request.form.get('season_name', '').strip()
        num_weeks   = int(request.form.get('num_weeks', 23))
        half_boundary = int(request.form.get('half_boundary_week', 11))
        start_date_str = request.form.get('start_date', '')

        if not season_name:
            flash('Season name is required.', 'danger')
            return redirect(url_for('admin.import_season'))

        if Season.query.filter_by(name=season_name).first():
            flash(f'Season "{season_name}" already exists.', 'danger')
            return redirect(url_for('admin.import_season'))

        try:
            wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True)
        except Exception as e:
            flash(f'Could not read spreadsheet: {e}', 'danger')
            return redirect(url_for('admin.import_season'))

        # Deactivate current active season
        Season.query.filter_by(is_active=True).update({'is_active': False})

        season = Season(
            name=season_name,
            num_weeks=num_weeks,
            half_boundary_week=half_boundary,
            is_active=True,
            bowling_format='single',
        )
        if start_date_str:
            season.start_date = date.fromisoformat(start_date_str)
        db.session.add(season)
        db.session.flush()

        # Create 4 teams
        teams = []
        for i in range(1, 5):
            tname = request.form.get(f'team{i}_name', '').strip() or f'Team {i}'
            t = Team(season_id=season.id, number=i, name=tname)
            db.session.add(t)
            teams.append(t)
        db.session.flush()
        team_map = {t.number: t for t in teams}

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

        # Post-season tournament weeks
        _add_postseason_weeks(season, num_weeks)
        db.session.flush()

        # ── Import roster from 'wkly alpha' sheet ──────────────────────────
        if 'wkly alpha' not in wb.sheetnames:
            flash('Spreadsheet is missing the "wkly alpha" sheet.', 'danger')
            db.session.rollback()
            return redirect(url_for('admin.import_season'))

        ws_alpha = wb['wkly alpha']
        bowler_added = bowler_skipped = 0

        for row in ws_alpha.iter_rows(min_row=8, max_row=70, min_col=1, max_col=21, values_only=True):
            last_name = row[0]
            if not last_name or not isinstance(last_name, str):
                continue
            if last_name.strip().lower() in SKIP_NAMES:
                continue

            first_name = (row[1] or '').strip() or None
            nickname   = (row[2] or '').strip() or None
            team_num   = row[3]
            curr_hcp   = int(row[9]) if row[9] else 0
            active     = str(row[15] or '').strip().lower() == 'yes'
            email      = (row[19] or '').strip() or None

            if team_num not in team_map:
                bowler_skipped += 1
                continue

            bowler = Bowler.query.filter_by(last_name=last_name.strip()).first()
            if not bowler:
                bowler = Bowler(last_name=last_name.strip(), first_name=first_name,
                                nickname=nickname, email=email)
                db.session.add(bowler)
                db.session.flush()
            else:
                if not bowler.nickname and nickname:
                    bowler.nickname = nickname
                if not bowler.email and email:
                    bowler.email = email

            roster_entry = Roster.query.filter_by(
                bowler_id=bowler.id, season_id=season.id
            ).first()
            if not roster_entry:
                roster_entry = Roster(
                    bowler_id=bowler.id, season_id=season.id,
                    team_id=team_map[team_num].id, active=active,
                    prior_handicap=curr_hcp, joined_week=1,
                )
                db.session.add(roster_entry)
            else:
                roster_entry.team_id = team_map[team_num].id
                roster_entry.active = active
                roster_entry.prior_handicap = curr_hcp
            bowler_added += 1

        db.session.flush()

        # ── Import per-bowler scores from individual sheets ─────────────────
        # matchup_num: teams 1&2 → 2 (B-side), teams 3&4 → 4 (B-side)
        def bowler_matchup_num(team_num):
            return 2 if team_num in (1, 2) else 4

        # Build a roster lookup: last_name → (bowler, team_num)
        roster_lookup = {}
        for row in ws_alpha.iter_rows(min_row=8, max_row=70, min_col=1, max_col=5, values_only=True):
            ln = row[0]
            tn = row[3]
            if ln and isinstance(ln, str) and ln.strip().lower() not in SKIP_NAMES and tn in team_map:
                roster_lookup[ln.strip()] = tn

        entries_added = 0
        for sheet_name in wb.sheetnames:
            if sheet_name in NON_BOWLER_SHEETS:
                continue
            ws_b = wb[sheet_name]
            rows = list(ws_b.iter_rows(values_only=True))
            if len(rows) < 11:
                continue

            week_row  = rows[6]   # row index 6 = row 7
            game1_row = rows[8]
            game2_row = rows[9]
            game3_row = rows[10]

            team_num = roster_lookup.get(sheet_name)
            if team_num is None:
                continue

            team_obj = team_map[team_num]
            bowler = Bowler.query.filter_by(last_name=sheet_name).first()
            if not bowler:
                continue

            matchup_num = bowler_matchup_num(team_num)
            side = 'B'

            for col in range(2, len(week_row)):
                wn = week_row[col]
                if not isinstance(wn, (int, float)):
                    continue
                wn = int(wn)
                if wn < 1 or wn > num_weeks:
                    continue

                g1 = game1_row[col] if col < len(game1_row) else None
                g2 = game2_row[col] if col < len(game2_row) else None
                g3 = game3_row[col] if col < len(game3_row) else None

                if g1 is None and g2 is None and g3 is None:
                    continue
                if g1 == 0 and g2 == 0 and g3 == 0:
                    continue

                entry = MatchupEntry(
                    season_id=season.id, week_num=wn,
                    matchup_num=matchup_num, team_id=team_obj.id,
                    bowler_id=bowler.id, is_blind=False, lane_side=side,
                    game1=int(g1) if g1 is not None else None,
                    game2=int(g2) if g2 is not None else None,
                    game3=int(g3) if g3 is not None else None,
                )
                db.session.add(entry)
                entries_added += 1

        # ── Import team points from 'team scoring' sheet ────────────────────
        from models import TeamPoints
        points_added = 0
        if 'team scoring' in wb.sheetnames:
            ws_ts = wb['team scoring']
            ts_rows = list(ws_ts.iter_rows(values_only=True))
            week_nums_entered = set()
            for row in ts_rows[7:]:
                if row[0] is None or not isinstance(row[0], (int, float)):
                    continue
                wn = int(row[0])
                if wn < 1 or wn > num_weeks:
                    continue
                # cols: T1A=2, T1B=3, T1tot=4, T2A=5, T2B=6, T2tot=7,
                #       T3A=8, T3B=9, T3tot=10, T4A=11, T4B=12, T4tot=13
                for ti, base_col in enumerate([2, 5, 8, 11], start=1):
                    if ti not in team_map:
                        continue
                    pts_a = row[base_col] or 0
                    pts_b = row[base_col + 1] or 0
                    mnum_a = 1 if ti in (1, 2) else 3
                    mnum_b = 2 if ti in (1, 2) else 4
                    team_id = team_map[ti].id
                    for mnum, pts in [(mnum_a, pts_a), (mnum_b, pts_b)]:
                        if pts > 0:
                            db.session.add(TeamPoints(
                                season_id=season.id, week_num=wn,
                                matchup_num=mnum, team_id=team_id,
                                points_earned=float(pts),
                            ))
                            points_added += 1
                week_nums_entered.add(wn)

            # Mark entered weeks
            for wn in week_nums_entered:
                wk = Week.query.filter_by(season_id=season.id, week_num=wn).first()
                if wk:
                    wk.is_entered = True

        db.session.commit()
        flash(
            f'Season "{season_name}" imported: {bowler_added} bowlers, '
            f'{entries_added} score entries, {points_added} team-point records.',
            'success'
        )
        return redirect(url_for('admin.season_detail', season_id=season.id))

    return render_template('admin/import_season.html')

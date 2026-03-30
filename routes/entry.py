"""
Score entry routes: weekly matchup entry, blind management, points calculation.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import (db, Season, Week, ScheduleEntry, MatchupEntry,
                    TeamPoints, Roster, Bowler)
from calculations import (score_matchup, score_position_night, calculate_handicap,
                          get_weekly_prizes)
from snapshots import save_snapshot
from config import Config

entry_bp = Blueprint('entry', __name__)


@entry_bp.route('/')
def index():
    active = Season.query.filter_by(is_active=True).first()
    if not active:
        flash('No active season. Create one in Admin.', 'warning')
        return redirect(url_for('admin.seasons'))
    return redirect(url_for('entry.week_list', season_id=active.id))


@entry_bp.route('/season/<int:season_id>')
def week_list(season_id):
    season = Season.query.get_or_404(season_id)
    weeks = Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()
    return render_template('entry/week_list.html', season=season, weeks=weeks)


@entry_bp.route('/season/<int:season_id>/week/<int:week_num>')
def week_entry(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()

    # Get all 4 matchups for this week
    matchups = (ScheduleEntry.query
                .filter_by(season_id=season_id, week_num=week_num)
                .order_by(ScheduleEntry.matchup_num)
                .all())

    # For each matchup, gather existing entries and active roster for each team
    matchup_data = []
    for sched in matchups:
        for team in [sched.team1, sched.team2]:
            entries = (MatchupEntry.query
                       .filter_by(season_id=season_id, week_num=week_num,
                                  matchup_num=sched.matchup_num, team_id=team.id)
                       .all())
            # Active roster for this team, sorted by last name
            roster = (Roster.query
                      .filter_by(season_id=season_id, team_id=team.id, active=True)
                      .join(Bowler)
                      .order_by(Bowler.last_name)
                      .all())
            matchup_data.append({
                'sched': sched,
                'team': team,
                'entries': entries,
                'roster': roster,
            })

    # Recon summary (only if week is entered)
    recon = None
    if week.is_entered:
        all_entries = MatchupEntry.query.filter_by(season_id=season_id, week_num=week_num).all()
        player_count = sum(1 for e in all_entries if not e.is_blind)
        blind_games  = sum(e.game_count for e in all_entries if e.is_blind)
        total_wood   = sum(
            e.total_pins + (
                (season.blind_handicap if e.is_blind
                 else calculate_handicap(e.bowler_id, season_id, week_num))
                * e.game_count
            )
            for e in all_entries
        )
        prizes = get_weekly_prizes(season_id, week_num)
        recon = {'player_count': player_count, 'blind_games': blind_games,
                 'total_wood': total_wood, 'prizes': prizes}

    return render_template('entry/week_entry.html',
                           season=season, week=week,
                           matchups=matchups,
                           matchup_data=matchup_data,
                           recon=recon)


@entry_bp.route('/season/<int:season_id>/week/<int:week_num>/matchup/<int:matchup_num>',
                methods=['GET', 'POST'])
def matchup_entry(season_id, week_num, matchup_num):
    """Score entry for one matchup (one lane pair)."""
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()
    sched = ScheduleEntry.query.filter_by(
        season_id=season_id, week_num=week_num, matchup_num=matchup_num
    ).first_or_404()

    teams = [sched.team1, sched.team2]

    if request.method == 'POST':
        # Delete existing entries for this matchup (re-entry overwrites)
        MatchupEntry.query.filter_by(
            season_id=season_id, week_num=week_num, matchup_num=matchup_num
        ).delete()
        TeamPoints.query.filter_by(
            season_id=season_id, week_num=week_num, matchup_num=matchup_num
        ).delete()

        for team in teams:
            side = 'A' if team.id == sched.team1_id else 'B'
            # Process each player row submitted for this team
            row_keys = [k for k in request.form if k.startswith(f't{team.number}_row_')]
            row_indices = sorted(set(
                int(k.split('_row_')[1].split('_')[0]) for k in row_keys
            ))

            for i in row_indices:
                prefix = f't{team.number}_row_{i}_'
                is_blind = request.form.get(f'{prefix}blind') == 'on'
                bowler_id_str = request.form.get(f'{prefix}bowler_id')
                bowler_id = int(bowler_id_str) if bowler_id_str and not is_blind else None

                # Skip completely empty rows
                games = []
                for g in range(1, 7):
                    val = request.form.get(f'{prefix}game{g}', '').strip()
                    games.append(int(val) if val.isdigit() else None)

                if not is_blind and bowler_id is None:
                    continue  # blank row

                entry = MatchupEntry(
                    season_id=season_id,
                    week_num=week_num,
                    matchup_num=matchup_num,
                    team_id=team.id,
                    bowler_id=bowler_id,
                    is_blind=is_blind,
                    lane_side=side,
                    game1=games[0], game2=games[1], game3=games[2],
                    game4=games[3], game5=games[4], game6=games[5],
                )
                db.session.add(entry)

        db.session.flush()

        # Calculate and save points
        if week.is_position_night:
            pts = score_position_night(season_id, week_num)
            for team_id, points in pts.items():
                tp = TeamPoints(
                    season_id=season_id, week_num=week_num,
                    matchup_num=matchup_num, team_id=team_id,
                    points_earned=points
                )
                db.session.add(tp)
        else:
            result = score_matchup(season_id, week_num, matchup_num)
            for team in teams:
                pts = result.get(team.id, 0)
                is_forfeit = result.get('forfeit') is not None
                tp = TeamPoints(
                    season_id=season_id, week_num=week_num,
                    matchup_num=matchup_num, team_id=team.id,
                    points_earned=pts,
                    is_forfeit=is_forfeit,
                )
                db.session.add(tp)

        db.session.commit()

        # Mark week as entered if all matchups are done
        all_matchups = ScheduleEntry.query.filter_by(
            season_id=season_id, week_num=week_num
        ).count()
        entered_matchups = (TeamPoints.query
                            .filter_by(season_id=season_id, week_num=week_num)
                            .with_entities(TeamPoints.matchup_num)
                            .distinct()
                            .count())
        if entered_matchups >= all_matchups:
            week.is_entered = True
            db.session.commit()
            # Auto-save snapshot
            try:
                save_snapshot(season_id, week_num, Config.SNAPSHOT_DIR)
            except Exception as e:
                flash(f'Snapshot error (scores saved): {e}', 'warning')

        flash(f'Matchup {matchup_num} scores saved.', 'success')
        return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))

    # GET: build form data
    existing = (MatchupEntry.query
                .filter_by(season_id=season_id, week_num=week_num, matchup_num=matchup_num)
                .all())

    # Group by team
    team_entries = {t.id: [] for t in teams}
    for e in existing:
        team_entries[e.team_id].append(e)

    # For each team, also get current handicaps for display
    roster_data = {}
    for team in teams:
        roster = (Roster.query
                  .filter_by(season_id=season_id, team_id=team.id, active=True)
                  .join(Bowler)
                  .order_by(Bowler.last_name)
                  .all())
        for r in roster:
            hcp = calculate_handicap(r.bowler_id, season_id, week_num)
            roster_data[r.bowler_id] = {'handicap': hcp, 'roster': r}

    return render_template('entry/matchup_entry.html',
                           season=season, week=week, sched=sched,
                           teams=teams, team_entries=team_entries,
                           roster_data=roster_data)


@entry_bp.route('/season/<int:season_id>/week/<int:week_num>/reconcile')
def reconcile(season_id, week_num):
    """Blinds reconciliation view."""
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()

    entries = MatchupEntry.query.filter_by(
        season_id=season_id, week_num=week_num
    ).all()

    # Build per-entry handicap and handicap wood
    entry_data = []
    for e in entries:
        if e.is_blind:
            hcp = season.blind_handicap
        else:
            hcp = calculate_handicap(e.bowler_id, season_id, week_num) if e.bowler_id else 0
        hcp_wood = e.total_pins + hcp * e.game_count
        entry_data.append({'entry': e, 'hcp': hcp, 'hcp_wood': hcp_wood})

    player_count = sum(1 for e in entries if not e.is_blind)
    blind_games  = sum(e.game_count for e in entries if e.is_blind)
    total_wood   = sum(d['hcp_wood'] for d in entry_data)

    return render_template('entry/reconcile.html',
                           season=season, week=week,
                           player_count=player_count,
                           blind_games=blind_games,
                           total_wood=total_wood,
                           entry_data=entry_data)

"""
Score entry routes: weekly matchup entry, blind management, points calculation.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from models import (db, Season, Week, ScheduleEntry, MatchupEntry,
                    TeamPoints, Roster, Bowler, TournamentEntry)
from calculations import (score_matchup, score_position_night, calculate_handicap,
                          get_weekly_prizes, get_team_standings, get_matchup_breakdown,
                          get_position_night_breakdown)
from snapshots import save_snapshot
from config import Config

entry_bp = Blueprint('entry', __name__)

_TOURNAMENT_LABELS = {
    'club_championship': 'Club Team Championship',
    'harry_russell': 'Harry E. Russell Championship',
    'chad_harris': 'Chad Harris Memorial Bowl',
    'shep_belyea': 'Shep Belyea Open',
}


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
    return render_template('entry/week_list.html', season=season, weeks=weeks,
                           tournament_labels=_TOURNAMENT_LABELS)


@entry_bp.route('/season/<int:season_id>/week/<int:week_num>/cancel', methods=['POST'])
def toggle_cancelled(season_id, week_num):
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()
    week.is_cancelled = not week.is_cancelled
    db.session.commit()
    status = 'cancelled' if week.is_cancelled else 'uncancelled'
    flash(f'Week {week_num} {status}.', 'success')
    return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))


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

    # Weekly team points (shown whether entered or partially entered)
    from models import Team
    teams_all = Team.query.filter_by(season_id=season_id).order_by(Team.number).all()
    wk_pts_raw = TeamPoints.query.filter_by(season_id=season_id, week_num=week_num).all()
    wk_pts_by_team = {}
    for tp in wk_pts_raw:
        wk_pts_by_team[tp.team_id] = wk_pts_by_team.get(tp.team_id, 0) + tp.points_earned
    weekly_team_pts = sorted(
        [{'team': t, 'points': wk_pts_by_team.get(t.id, 0)} for t in teams_all],
        key=lambda x: x['points'], reverse=True
    )

    # Points per matchup: {matchup_num: {team_id: points}}
    pts_by_matchup = {}
    for tp in wk_pts_raw:
        pts_by_matchup.setdefault(tp.matchup_num, {})[tp.team_id] = tp.points_earned

    # Per-matchup game breakdown for display
    breakdown_by_matchup = {}
    breakdown_by_pairing = {}
    if week.is_position_night:
        for pnum in [1, 2]:
            bd = get_position_night_breakdown(season_id, week_num, pnum)
            if bd:
                breakdown_by_pairing[pnum] = bd
    else:
        for sched in matchups:
            bd = get_matchup_breakdown(season_id, week_num, sched.matchup_num)
            if bd:
                breakdown_by_matchup[sched.matchup_num] = bd

    # Prev / next week navigation
    all_week_nums = [w.week_num for w in
                     Week.query.filter_by(season_id=season_id).order_by(Week.week_num).all()]
    wk_idx = all_week_nums.index(week_num) if week_num in all_week_nums else -1
    prev_week_num = all_week_nums[wk_idx - 1] if wk_idx > 0 else None
    next_week_num = all_week_nums[wk_idx + 1] if wk_idx >= 0 and wk_idx < len(all_week_nums) - 1 else None

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
                           recon=recon,
                           weekly_team_pts=weekly_team_pts,
                           pts_by_matchup=pts_by_matchup,
                           breakdown_by_matchup=breakdown_by_matchup,
                           breakdown_by_pairing=breakdown_by_pairing,
                           prev_week_num=prev_week_num,
                           next_week_num=next_week_num,
                           tournament_labels=_TOURNAMENT_LABELS)


@entry_bp.route('/season/<int:season_id>/week/<int:week_num>/clear-tournament-entries', methods=['POST'])
def clear_tournament_entries(season_id, week_num):
    from flask_login import current_user
    if not current_user.is_editor:
        abort(403)
    TournamentEntry.query.filter_by(season_id=season_id, week_num=week_num).delete()
    db.session.commit()
    flash(f'Tournament entries for week {week_num} cleared.', 'info')
    return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))


@entry_bp.route('/season/<int:season_id>/week/<int:week_num>/generate-test-entries', methods=['POST'])
def generate_test_entries(season_id, week_num):
    from flask_login import current_user
    if not current_user.is_editor:
        abort(403)
    import random
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()

    if not week.tournament_type or week.tournament_type == 'club_championship':
        flash('Test entries only apply to individual tournament weeks.', 'warning')
        return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))

    TournamentEntry.query.filter_by(season_id=season_id, week_num=week_num).delete()

    is_harry = week.tournament_type == 'harry_russell'
    num_games = 5 if is_harry else 3

    roster = (Roster.query
              .filter_by(season_id=season_id, active=True)
              .join(Bowler)
              .order_by(Bowler.last_name)
              .all())

    for r in roster:
        hcp = 0 if is_harry else calculate_handicap(r.bowler_id, season_id, week_num)
        games = [random.randint(130, 220) for _ in range(num_games)]
        db.session.add(TournamentEntry(
            season_id=season_id,
            week_num=week_num,
            bowler_id=r.bowler_id,
            handicap=hcp,
            game1=games[0],
            game2=games[1],
            game3=games[2],
            game4=games[3] if num_games > 3 else None,
            game5=games[4] if num_games > 4 else None,
        ))

    db.session.commit()
    flash(f'Generated test entries for {len(roster)} bowlers.', 'success')
    return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))


def _auto_assign_position_night(season_id, position_week_num):
    """
    Update ScheduleEntry for a position night based on standings through the prior week.
    Regular position night: top-2 on matchups 1&2, bottom-2 on matchups 3&4.
    Club Championship: top-2 on all 4 matchups (only those 2 teams bowl).
    """
    from models import Week
    pos_week = Week.query.filter_by(season_id=season_id, week_num=position_week_num).first()
    is_club_championship = (pos_week and pos_week.tournament_type == 'club_championship')

    standings = get_team_standings(season_id, through_week=position_week_num - 1)
    if len(standings) < 2:
        return
    top_a, top_b = standings[0]['team'], standings[1]['team']

    if is_club_championship:
        # Only the top 2 teams bowl, on all 4 lane pairs
        assignments = {
            1: (top_a.id, top_b.id),
            2: (top_a.id, top_b.id),
            3: (top_a.id, top_b.id),
            4: (top_a.id, top_b.id),
        }
    else:
        if len(standings) < 4:
            return
        bot_a, bot_b = standings[2]['team'], standings[3]['team']
        assignments = {
            1: (top_a.id, top_b.id),
            2: (top_a.id, top_b.id),
            3: (bot_a.id, bot_b.id),
            4: (bot_a.id, bot_b.id),
        }
    for matchup_num, (t1_id, t2_id) in assignments.items():
        sched = ScheduleEntry.query.filter_by(
            season_id=season_id, week_num=position_week_num,
            matchup_num=matchup_num
        ).first()
        if sched:
            sched.team1_id = t1_id
            sched.team2_id = t2_id
        else:
            db.session.add(ScheduleEntry(
                season_id=season_id, week_num=position_week_num,
                matchup_num=matchup_num, team1_id=t1_id, team2_id=t2_id
            ))


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
                bowler_id_str = request.form.get(f'{prefix}bowler_id', '').strip()
                is_blind = (bowler_id_str == 'BLIND')
                bowler_id = int(bowler_id_str) if (bowler_id_str and not is_blind
                                                    and bowler_id_str.isdigit()) else None

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
            # Delete ALL TeamPoints for the week before re-inserting — position night
            # points are calculated from all matchups together, so saving any single
            # matchup must replace the full set to avoid double-counting.
            TeamPoints.query.filter_by(season_id=season_id, week_num=week_num).delete()
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

        # If the next week is an un-entered position night, update its lane assignments
        next_pos = Week.query.filter_by(
            season_id=season_id, week_num=week_num + 1,
            is_position_night=True, is_entered=False
        ).first()
        if next_pos:
            _auto_assign_position_night(season_id, week_num + 1)
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

    breakdown = get_matchup_breakdown(season_id, week_num, matchup_num)
    return render_template('entry/matchup_entry.html',
                           season=season, week=week, sched=sched,
                           teams=teams, team_entries=team_entries,
                           roster_data=roster_data, breakdown=breakdown)


@entry_bp.route('/season/<int:season_id>/week/<int:week_num>/position/<int:pairing_num>',
                methods=['GET', 'POST'])
def position_entry(season_id, week_num, pairing_num):
    """
    Combined score entry for one position-night team pairing.
    pairing_num=1 → matchup_nums 1 & 2 (top-2 teams)
    pairing_num=2 → matchup_nums 3 & 4 (bottom-2 teams)
    """
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()
    if not week.is_position_night:
        flash('This week is not a position night.', 'warning')
        return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))

    is_club_championship = (week.tournament_type == 'club_championship')
    if is_club_championship:
        matchup_nums = [1, 2]   # one pairing covers both lane pairs
    else:
        matchup_nums = [1, 2] if pairing_num == 1 else [3, 4]

    scheds = (ScheduleEntry.query
              .filter_by(season_id=season_id, week_num=week_num)
              .filter(ScheduleEntry.matchup_num.in_(matchup_nums))
              .order_by(ScheduleEntry.matchup_num)
              .all())
    if not scheds:
        flash('No schedule entries found for this pairing.', 'warning')
        return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))

    team1 = scheds[0].team1
    team2 = scheds[0].team2
    teams = [team1, team2]

    if request.method == 'POST':
        # Delete existing entries for both matchups in this pairing
        MatchupEntry.query.filter(
            MatchupEntry.season_id == season_id,
            MatchupEntry.week_num == week_num,
            MatchupEntry.matchup_num.in_(matchup_nums)
        ).delete(synchronize_session=False)

        for sched in scheds:
            mnum = sched.matchup_num
            for team in teams:
                side = 'A' if team.id == sched.team1_id else 'B'
                prefix_base = f'm{mnum}_t{team.number}_row_'
                row_keys = [k for k in request.form if k.startswith(prefix_base)]
                row_indices = sorted(set(
                    int(k[len(prefix_base):].split('_')[0]) for k in row_keys
                ))
                for i in row_indices:
                    prefix = f'm{mnum}_t{team.number}_row_{i}_'
                    bowler_id_str = request.form.get(f'{prefix}bowler_id', '').strip()
                    is_blind = (bowler_id_str == 'BLIND')
                    bowler_id = int(bowler_id_str) if (bowler_id_str and not is_blind
                                                        and bowler_id_str.isdigit()) else None
                    games = []
                    for g in range(1, 7):
                        val = request.form.get(f'{prefix}game{g}', '').strip()
                        games.append(int(val) if val.isdigit() else None)
                    if not is_blind and bowler_id is None:
                        continue
                    db.session.add(MatchupEntry(
                        season_id=season_id, week_num=week_num,
                        matchup_num=mnum, team_id=team.id,
                        bowler_id=bowler_id, is_blind=is_blind, lane_side=side,
                        game1=games[0], game2=games[1], game3=games[2],
                        game4=games[3], game5=games[4], game6=games[5],
                    ))

        db.session.flush()

        # Recalculate position night points (delete all week's points, re-insert once)
        TeamPoints.query.filter_by(season_id=season_id, week_num=week_num).delete()
        pts = score_position_night(season_id, week_num)
        for team_id, points in pts.items():
            db.session.add(TeamPoints(
                season_id=season_id, week_num=week_num,
                matchup_num=matchup_nums[0], team_id=team_id,
                points_earned=points
            ))

        db.session.commit()

        # Club championship has only one pairing; regular position night needs both saved.
        other_matchup_nums = [3, 4] if pairing_num == 1 else [1, 2]
        other_has_entries = is_club_championship or MatchupEntry.query.filter(
            MatchupEntry.season_id == season_id,
            MatchupEntry.week_num == week_num,
            MatchupEntry.matchup_num.in_(other_matchup_nums)
        ).count() > 0
        if other_has_entries:
            week.is_entered = True
            db.session.commit()
            try:
                save_snapshot(season_id, week_num, Config.SNAPSHOT_DIR)
            except Exception as e:
                flash(f'Snapshot error (scores saved): {e}', 'warning')

        flash(f'Position night pairing {pairing_num} scores saved.', 'success')
        return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))

    # GET: load existing entries for both matchups
    existing = {}
    for sched in scheds:
        for team in teams:
            key = (sched.matchup_num, team.id)
            existing[key] = (MatchupEntry.query
                             .filter_by(season_id=season_id, week_num=week_num,
                                        matchup_num=sched.matchup_num, team_id=team.id)
                             .all())

    # Handicaps for all bowlers on these teams
    roster_data = {}
    for team in teams:
        roster = (Roster.query
                  .filter_by(season_id=season_id, team_id=team.id, active=True)
                  .join(Bowler)
                  .order_by(Bowler.last_name)
                  .all())
        for r in roster:
            roster_data[r.bowler_id] = {
                'handicap': calculate_handicap(r.bowler_id, season_id, week_num),
                'roster': r,
            }

    return render_template('entry/position_entry.html',
                           season=season, week=week,
                           pairing_num=pairing_num,
                           scheds=scheds, teams=teams,
                           existing=existing,
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


# ---------------------------------------------------------------------------
# Tournament entry (Harry Russell, Chad Harris, Shep Belyea, Club Championship)
# ---------------------------------------------------------------------------

@entry_bp.route('/season/<int:season_id>/week/<int:week_num>/tournament',
                methods=['GET', 'POST'])
def tournament_entry(season_id, week_num):
    season = Season.query.get_or_404(season_id)
    week = Week.query.filter_by(season_id=season_id, week_num=week_num).first_or_404()
    if not week.tournament_type:
        flash('This week is not a tournament week.', 'warning')
        return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))

    tt = week.tournament_type
    label = _TOURNAMENT_LABELS.get(tt, tt)

    # Harry Russell: all bowlers ever (active + inactive); others: active only
    if tt == 'harry_russell':
        all_bowlers = (Bowler.query
                       .join(Roster, Roster.bowler_id == Bowler.id)
                       .filter(Roster.season_id == season_id)
                       .order_by(Bowler.last_name)
                       .all())
    else:
        all_bowlers = (Bowler.query
                       .join(Roster, Roster.bowler_id == Bowler.id)
                       .filter(Roster.season_id == season_id, Roster.active == True)
                       .order_by(Bowler.last_name)
                       .all())

    num_games = 5 if tt == 'harry_russell' else 3
    use_handicap = (tt != 'harry_russell')

    if request.method == 'POST':
        # Delete existing entries for this tournament week
        TournamentEntry.query.filter_by(
            season_id=season_id, week_num=week_num
        ).delete()

        for key in request.form:
            if not key.startswith('bowler_'):
                continue
            row_id = key[len('bowler_'):]
            bowler_val = request.form.get(f'bowler_{row_id}', '').strip()
            if not bowler_val:
                continue

            games = []
            for g in range(1, num_games + 1):
                val = request.form.get(f'game{g}_{row_id}', '').strip()
                games.append(int(val) if val.isdigit() else None)

            if all(g is None for g in games):
                continue

            hcp = 0
            if use_handicap:
                hcp_val = request.form.get(f'hcp_{row_id}', '').strip()
                hcp = int(hcp_val) if hcp_val.isdigit() else 0

            if bowler_val == 'WRITE_IN':
                guest = request.form.get(f'guest_name_{row_id}', '').strip()
                if not guest:
                    continue
                te = TournamentEntry(
                    season_id=season_id, week_num=week_num,
                    guest_name=guest, handicap=hcp,
                    game1=games[0] if len(games) > 0 else None,
                    game2=games[1] if len(games) > 1 else None,
                    game3=games[2] if len(games) > 2 else None,
                    game4=games[3] if len(games) > 3 else None,
                    game5=games[4] if len(games) > 4 else None,
                )
            else:
                bowler_id = int(bowler_val)
                if use_handicap and hcp == 0:
                    hcp = calculate_handicap(bowler_id, season_id, week_num)
                te = TournamentEntry(
                    season_id=season_id, week_num=week_num,
                    bowler_id=bowler_id, handicap=hcp,
                    game1=games[0] if len(games) > 0 else None,
                    game2=games[1] if len(games) > 1 else None,
                    game3=games[2] if len(games) > 2 else None,
                    game4=games[3] if len(games) > 3 else None,
                    game5=games[4] if len(games) > 4 else None,
                )
            db.session.add(te)

        db.session.commit()
        week.is_entered = True
        db.session.commit()
        flash(f'{label} scores saved.', 'success')
        return redirect(url_for('entry.week_entry', season_id=season_id, week_num=week_num))

    # GET — load existing entries
    existing = TournamentEntry.query.filter_by(
        season_id=season_id, week_num=week_num
    ).all()

    # Pre-compute handicaps for display
    bowler_handicaps = {}
    for b in all_bowlers:
        bowler_handicaps[b.id] = calculate_handicap(b.id, season_id, week_num)

    return render_template('entry/tournament_entry.html',
                           season=season, week=week, label=label,
                           tournament_type=tt,
                           all_bowlers=all_bowlers,
                           existing=existing,
                           num_games=num_games,
                           use_handicap=use_handicap,
                           bowler_handicaps=bowler_handicaps)

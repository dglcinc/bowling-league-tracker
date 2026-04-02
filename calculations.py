"""
All bowling stat calculations for the league tracker.
All functions take SQLAlchemy session/model data and return plain Python values.
No derived values are stored — everything is computed from raw matchup_entries.
"""

from math import floor
from models import db, MatchupEntry, Roster, Season, TeamPoints, ScheduleEntry


# ---------------------------------------------------------------------------
# Core helper: fetch all entries for a bowler in a season
# ---------------------------------------------------------------------------

def get_bowler_entries(bowler_id, season_id):
    """
    Returns list of MatchupEntry for a bowler, sorted by week.
    Tournament weeks are excluded so they don't count toward season averages/handicaps.
    """
    from models import Week
    tournament_weeks = {
        w.week_num for w in
        Week.query.filter_by(season_id=season_id).filter(
            Week.tournament_type.isnot(None)
        ).all()
    }
    entries = (MatchupEntry.query
               .filter_by(bowler_id=bowler_id, season_id=season_id, is_blind=False)
               .order_by(MatchupEntry.week_num)
               .all())
    return [e for e in entries if e.week_num not in tournament_weeks]


# ---------------------------------------------------------------------------
# Handicap calculation
# ---------------------------------------------------------------------------

def calculate_handicap(bowler_id, season_id, for_week, entries=None):
    """
    Returns the handicap that applies when bowling in for_week.

    Rules:
      - While cumulative games through (for_week - 1) < 6:
          * Has prior year handicap  → use prior_handicap unchanged
          * No prior handicap (new)  → ROUND((base - tonight_avg) * factor, 0)
            where tonight_avg = this week's pins / this week's games
      - Once cumulative games through (for_week - 1) >= 6:
          → ROUND((base - prior_week_running_avg) * factor, 0)
    """
    roster = Roster.query.filter_by(bowler_id=bowler_id, season_id=season_id).first()
    if not roster:
        return 0

    season = Season.query.get(season_id)
    base = season.handicap_base      # 200
    factor = season.handicap_factor  # 0.9
    prior_hcp = roster.prior_handicap or 0

    if entries is None:
        entries = get_bowler_entries(bowler_id, season_id)

    # Entries from weeks before this week
    prev_entries = [e for e in entries if e.week_num < for_week]
    cumulative_games = sum(e.game_count for e in prev_entries)
    cumulative_pins = sum(e.total_pins for e in prev_entries)

    if cumulative_games < 6:
        # Still in first-6-games zone — use prior handicap, or calculate from tonight
        if prior_hcp > 0:
            return prior_hcp
        else:
            # New bowler: calculate from this week's games if available
            this_week = [e for e in entries if e.week_num == for_week]
            if this_week:
                week_entry = this_week[0]
                wk_games = week_entry.game_count
                wk_pins = week_entry.total_pins
                if wk_games > 0:
                    tonight_avg = wk_pins / wk_games
                    return round((base - tonight_avg) * factor)
            return 0  # hasn't bowled yet
    else:
        # Established: use prior week's running average
        prior_avg = round(cumulative_pins / cumulative_games)
        return round((base - prior_avg) * factor)


# ---------------------------------------------------------------------------
# Bowler season stats
# ---------------------------------------------------------------------------

def get_bowler_stats(bowler_id, season_id, through_week=None):
    """
    Returns a dict of all YTD stats for a bowler through a given week.
    If through_week is None, uses all available weeks.
    """
    entries = get_bowler_entries(bowler_id, season_id)
    if through_week is not None:
        entries = [e for e in entries if e.week_num <= through_week]

    season = Season.query.get(season_id)
    roster = Roster.query.filter_by(bowler_id=bowler_id, season_id=season_id).first()
    prior_hcp = roster.prior_handicap if roster else 0

    cumulative_pins = 0
    cumulative_games = 0
    second_half_pins = 0
    ytd_high_game_scratch = 0
    ytd_high_game_hcp = 0
    ytd_high_series_scratch = 0
    ytd_high_series_hcp = 0
    red_pins_total = 0

    weekly_stats = []

    for entry in entries:
        week_num = entry.week_num
        all_games = entry.all_games
        n1 = entry.games_night1
        n2 = entry.games_night2

        if not all_games:
            continue

        # Handicap for this week
        hcp = calculate_handicap(bowler_id, season_id, week_num, entries)

        week_pins = entry.total_pins
        week_games = entry.game_count
        cumulative_pins += week_pins
        cumulative_games += week_games

        # Running average after this week
        running_avg = round(cumulative_pins / cumulative_games) if cumulative_games else 0

        # Second half accumulation (weeks after half boundary)
        if week_num > season.half_boundary_week:
            second_half_pins += week_pins

        # High game scratch this week
        wk_high_scratch = max(all_games) if all_games else 0
        # High game with handicap
        wk_high_hcp_game = (wk_high_scratch + hcp) if wk_high_scratch > 0 else 0

        # High series scratch: better of night 1 or night 2
        series_n1 = sum(n1)
        series_n2 = sum(n2)
        wk_high_series_scratch = max(series_n1, series_n2)

        # High series with handicap: winning series + hcp * games in that set
        if wk_high_series_scratch > 0:
            if series_n1 >= series_n2:
                winning_game_count = len(n1)
            else:
                winning_game_count = len(n2)
            wk_high_series_hcp = wk_high_series_scratch + hcp * winning_game_count
        else:
            wk_high_series_hcp = 0

        # Update YTD highs
        ytd_high_game_scratch = max(ytd_high_game_scratch, wk_high_scratch)
        ytd_high_game_hcp = max(ytd_high_game_hcp, wk_high_hcp_game)
        ytd_high_series_scratch = max(ytd_high_series_scratch, wk_high_series_scratch)
        ytd_high_series_hcp = max(ytd_high_series_hcp, wk_high_series_hcp)

        weekly_stats.append({
            'week_num': week_num,
            'games': all_games,
            'week_pins': week_pins,
            'week_games': week_games,
            'cumulative_pins': cumulative_pins,
            'cumulative_games': cumulative_games,
            'running_avg': running_avg,
            'handicap': hcp,
            'high_game_scratch': wk_high_scratch,
            'high_game_hcp': wk_high_hcp_game,
            'high_series_scratch': wk_high_series_scratch,
            'high_series_hcp': wk_high_series_hcp,
        })

    # Current handicap = handicap for the NEXT week after the last one entered
    last_week = max((e.week_num for e in entries), default=0)
    current_hcp = calculate_handicap(bowler_id, season_id, last_week + 1, entries)

    # "Use this handicap" for display: prior hcp if <=3 games, else current calc
    display_hcp = prior_hcp if cumulative_games <= 3 else current_hcp

    return {
        'bowler_id': bowler_id,
        'season_id': season_id,
        'cumulative_pins': cumulative_pins,
        'cumulative_games': cumulative_games,
        'running_avg': round(cumulative_pins / cumulative_games) if cumulative_games else 0,
        'current_handicap': current_hcp,
        'display_handicap': display_hcp,
        'prior_handicap': prior_hcp,
        'second_half_pins': second_half_pins,
        'ytd_high_game_scratch': ytd_high_game_scratch,
        'ytd_high_game_hcp': ytd_high_game_hcp,
        'ytd_high_series_scratch': ytd_high_series_scratch,
        'ytd_high_series_hcp': ytd_high_series_hcp,
        'weekly_stats': weekly_stats,
        'weeks_bowled': len(weekly_stats),
        'iron_man_candidate': True,  # updated below
    }


# ---------------------------------------------------------------------------
# Team matchup scoring
# ---------------------------------------------------------------------------

def score_matchup(season_id, week_num, matchup_num):
    """
    Calculates and returns points for each team in a matchup.
    Returns dict: {team_id: points, ...} plus details.

    For regular weeks: 1 pt per game (higher hcp total wins) + 1 pt series.
    For position nights: aggregation happens at a higher level (score_position_night).
    Forfeit: if one team has 0 bowlers, present team gets all 4 points.
    """
    season = Season.query.get(season_id)
    sched = ScheduleEntry.query.filter_by(
        season_id=season_id, week_num=week_num, matchup_num=matchup_num
    ).first()

    if not sched:
        return {}

    team1_id = sched.team1_id
    team2_id = sched.team2_id

    t1_entries = MatchupEntry.query.filter_by(
        season_id=season_id, week_num=week_num,
        matchup_num=matchup_num, team_id=team1_id
    ).all()
    t2_entries = MatchupEntry.query.filter_by(
        season_id=season_id, week_num=week_num,
        matchup_num=matchup_num, team_id=team2_id
    ).all()

    # Check forfeit
    t1_has_bowlers = any(not e.is_blind for e in t1_entries)
    t2_has_bowlers = any(not e.is_blind for e in t2_entries)

    if not t1_has_bowlers and not t2_has_bowlers:
        return {team1_id: 0, team2_id: 0, 'forfeit': 'both'}
    if not t1_has_bowlers:
        return {team1_id: 0, team2_id: 4, 'forfeit': team1_id}
    if not t2_has_bowlers:
        return {team1_id: 4, team2_id: 0, 'forfeit': team2_id}

    # Build per-game handicap totals for each team
    def team_game_hcp_totals(entries, team_id):
        """Returns [game1_hcp_total, game2_hcp_total, game3_hcp_total]"""
        game_totals = [0, 0, 0]
        for entry in entries:
            if entry.is_blind:
                hcp = season.blind_handicap
                scratch_games = [season.blind_scratch] * min(entry.game_count or 3, 3)
            else:
                hcp = calculate_handicap(entry.bowler_id, season_id, week_num)
                scratch_games = entry.games_night1 or []

            for i, score in enumerate(scratch_games[:3]):
                game_totals[i] += score + hcp

        return game_totals

    t1_game_totals = team_game_hcp_totals(t1_entries, team1_id)
    t2_game_totals = team_game_hcp_totals(t2_entries, team2_id)

    t1_pts = 0
    t2_pts = 0
    game_detail = []

    # Points per game
    for g in range(3):
        t1_g = t1_game_totals[g]
        t2_g = t2_game_totals[g]
        if t1_g > t2_g:
            t1_pts += 1
        elif t2_g > t1_g:
            t2_pts += 1
        # Tie: no point awarded
        game_detail.append({'team1_total': t1_g, 'team2_total': t2_g})

    # Series point
    t1_series = sum(t1_game_totals)
    t2_series = sum(t2_game_totals)
    if t1_series > t2_series:
        t1_pts += 1
    elif t2_series > t1_series:
        t2_pts += 1

    return {
        team1_id: t1_pts,
        team2_id: t2_pts,
        'game_detail': game_detail,
        'team1_series': t1_series,
        'team2_series': t2_series,
        'forfeit': None,
    }


def get_matchup_breakdown(season_id, week_num, matchup_num):
    """
    Returns a structured breakdown of one matchup suitable for display.
    {
      'team1': Team, 'team2': Team,
      'games': [{'label':'G1','t1':X,'t2':Y,'winner':team_id_or_None}, ...],  # 3 game rows
      'series': {'t1': X, 't2': Y, 'winner': team_id_or_None},
      'pts': {team1_id: n, team2_id: n},
    }
    Returns None if no entries exist yet.
    """
    sched = ScheduleEntry.query.filter_by(
        season_id=season_id, week_num=week_num, matchup_num=matchup_num
    ).first()
    if not sched:
        return None
    entries_exist = MatchupEntry.query.filter_by(
        season_id=season_id, week_num=week_num, matchup_num=matchup_num
    ).count()
    if not entries_exist:
        return None

    result = score_matchup(season_id, week_num, matchup_num)
    if not result or result.get('forfeit') == 'both':
        return None

    gd = result.get('game_detail', [])
    t1_id, t2_id = sched.team1_id, sched.team2_id

    def winner(t1_val, t2_val):
        if t1_val > t2_val:
            return t1_id
        if t2_val > t1_val:
            return t2_id
        return None  # tie

    games = [
        {'label': f'G{i+1}',
         't1': gd[i]['team1_total'] if i < len(gd) else 0,
         't2': gd[i]['team2_total'] if i < len(gd) else 0,
         'winner': winner(gd[i]['team1_total'], gd[i]['team2_total']) if i < len(gd) else None}
        for i in range(3)
    ]
    t1_ser = result.get('team1_series', 0)
    t2_ser = result.get('team2_series', 0)

    return {
        'team1': sched.team1,
        'team2': sched.team2,
        'games': games,
        'series': {'t1': t1_ser, 't2': t2_ser, 'winner': winner(t1_ser, t2_ser)},
        'pts': {t1_id: result.get(t1_id, 0), t2_id: result.get(t2_id, 0)},
    }


def score_position_night(season_id, week_num):
    """
    Position night: aggregate all matchup sheets for each team pairing.
    Returns {team_id: points} — 2 pts per game (3 games) + 2 pts series = max 8 per pairing.
    """
    season = Season.query.get(season_id)
    schedule = ScheduleEntry.query.filter_by(
        season_id=season_id, week_num=week_num
    ).all()

    # Find unique team pairings
    pairings = {}
    for sched in schedule:
        key = tuple(sorted([sched.team1_id, sched.team2_id]))
        if key not in pairings:
            pairings[key] = []
        pairings[key].append(sched.matchup_num)

    result = {}
    for (t1_id, t2_id), matchup_nums in pairings.items():
        # Aggregate game hcp totals across all matchups in this pairing
        agg_t1 = [0, 0, 0]
        agg_t2 = [0, 0, 0]

        for mnum in matchup_nums:
            t1_entries = MatchupEntry.query.filter_by(
                season_id=season_id, week_num=week_num,
                matchup_num=mnum, team_id=t1_id
            ).all()
            t2_entries = MatchupEntry.query.filter_by(
                season_id=season_id, week_num=week_num,
                matchup_num=mnum, team_id=t2_id
            ).all()

            for entries, agg in [(t1_entries, agg_t1), (t2_entries, agg_t2)]:
                for entry in entries:
                    if entry.is_blind:
                        hcp = season.blind_handicap
                        games = [season.blind_scratch] * (entry.game_count or 3)
                    else:
                        hcp = calculate_handicap(entry.bowler_id, season_id, week_num)
                        games = entry.games_night1 or []
                    for i, score in enumerate(games[:3]):
                        agg[i] += score + hcp

        t1_pts = 0
        t2_pts = 0
        for g in range(3):
            if agg_t1[g] > agg_t2[g]:
                t1_pts += 2
            elif agg_t2[g] > agg_t1[g]:
                t2_pts += 2

        t1_series = sum(agg_t1)
        t2_series = sum(agg_t2)
        if t1_series > t2_series:
            t1_pts += 2
        elif t2_series > t1_series:
            t2_pts += 2

        result[t1_id] = result.get(t1_id, 0) + t1_pts
        result[t2_id] = result.get(t2_id, 0) + t2_pts

    return result


# ---------------------------------------------------------------------------
# Team standings
# ---------------------------------------------------------------------------

def get_team_standings(season_id, half=None, through_week=None):
    """
    Returns list of {team, points} sorted by points desc.
    half=1 → first half weeks, half=2 → second half, None → full season.
    through_week → cap at that week number (applied on top of half filter).
    """
    season = Season.query.get(season_id)
    query = TeamPoints.query.filter_by(season_id=season_id)

    if half == 1:
        query = query.filter(TeamPoints.week_num <= season.half_boundary_week)
    elif half == 2:
        query = query.filter(TeamPoints.week_num > season.half_boundary_week)

    if through_week is not None:
        query = query.filter(TeamPoints.week_num <= through_week)

    all_points = query.all()

    standings = {}
    for tp in all_points:
        if tp.team_id not in standings:
            standings[tp.team_id] = {'team': tp.team, 'points': 0}
        standings[tp.team_id]['points'] += tp.points_earned

    return sorted(standings.values(), key=lambda x: x['points'], reverse=True)


# ---------------------------------------------------------------------------
# Wkly Alpha roster stats (for the printable sheet)
# ---------------------------------------------------------------------------

def get_wkly_alpha(season_id, as_of_week):
    """
    Returns all active bowlers' stats as of as_of_week, sorted alphabetically.
    High game/series pulled from PRIOR week (as_of_week - 1).
    Handicap shown is 'display_handicap' (use-this-handicap logic).
    """
    from models import Bowler
    roster_entries = (Roster.query
                      .filter_by(season_id=season_id, active=True)
                      .all())

    rows = []
    for r in roster_entries:
        stats = get_bowler_stats(r.bowler_id, season_id, through_week=as_of_week)
        prior_stats = get_bowler_stats(r.bowler_id, season_id,
                                       through_week=max(as_of_week - 1, 0))
        rows.append({
            'bowler': r.bowler,
            'team': r.team,
            'total_pins': stats['cumulative_pins'],
            'second_half_pins': stats['second_half_pins'],
            'games': stats['cumulative_games'],
            'average': stats['running_avg'],
            'display_handicap': stats['display_handicap'],
            'current_handicap': stats['current_handicap'],
            'prior_handicap': r.prior_handicap,
            # High game/series from prior week for print
            'high_game_scratch': prior_stats['ytd_high_game_scratch'],
            'high_game_hcp': prior_stats['ytd_high_game_hcp'],
            'high_series_scratch': prior_stats['ytd_high_series_scratch'],
            'high_series_hcp': prior_stats['ytd_high_series_hcp'],
        })

    rows.sort(key=lambda r: r['bowler'].last_name)
    return rows


# ---------------------------------------------------------------------------
# Iron Man tracking
# ---------------------------------------------------------------------------

def get_iron_man_status(season_id, through_week):
    """
    Returns list of bowlers who have bowled every week so far.
    A bowler must have at least one entry in each week from their joined_week.
    """
    roster_entries = Roster.query.filter_by(season_id=season_id, active=True).all()
    weeks_so_far = list(range(1, through_week + 1))

    iron_men = []
    for r in roster_entries:
        entries = get_bowler_entries(r.bowler_id, season_id)
        bowled_weeks = {e.week_num for e in entries}
        required_weeks = [w for w in weeks_so_far if w >= r.joined_week]
        if all(w in bowled_weeks for w in required_weeks):
            iron_men.append(r.bowler)

    return iron_men


# ---------------------------------------------------------------------------
# Most Improved calculation
# ---------------------------------------------------------------------------

def get_most_improved(season_id, through_week):
    """
    Returns bowlers sorted by (current_avg - prior_year_avg) descending.
    Prior year avg back-calculated from prior_handicap: avg ≈ 200 - (prior_hcp / 0.9)
    """
    season = Season.query.get(season_id)
    roster_entries = Roster.query.filter_by(season_id=season_id, active=True).all()

    results = []
    for r in roster_entries:
        stats = get_bowler_stats(r.bowler_id, season_id, through_week)
        if stats['cumulative_games'] < 9:
            continue  # not enough games for meaningful comparison
        prior_avg = (
            round(season.handicap_base - (r.prior_handicap / season.handicap_factor))
            if r.prior_handicap else None
        )
        improvement = (
            (stats['running_avg'] - prior_avg) if prior_avg is not None else None
        )
        results.append({
            'bowler': r.bowler,
            'current_avg': stats['running_avg'],
            'prior_avg': prior_avg,
            'improvement': improvement,
        })

    results.sort(key=lambda x: (x['improvement'] or -999), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Weekly prizes
# ---------------------------------------------------------------------------

def get_weekly_team_points(season_id):
    """
    Returns per-week team points breakdown for the scoring grid.
    Returns (weeks_data, teams) where:
      weeks_data = [{'week': Week, 'teams': [{'team', 'pts_a', 'pts_b', 'total', 'cumul'}],
                     'grand_total': float}]
      teams = [Team] sorted by number
    cumulative totals accumulate across all weeks.
    """
    from models import Team, Week

    teams = (Team.query
             .filter_by(season_id=season_id)
             .order_by(Team.number)
             .all())

    weeks = (Week.query
             .filter_by(season_id=season_id, is_entered=True, is_cancelled=False)
             .order_by(Week.week_num)
             .all())

    cumulative = {t.id: 0.0 for t in teams}
    weeks_data = []

    for week in weeks:
        all_pts = (TeamPoints.query
                   .filter_by(season_id=season_id, week_num=week.week_num)
                   .order_by(TeamPoints.matchup_num)
                   .all())

        by_team = {}
        for tp in all_pts:
            by_team.setdefault(tp.team_id, []).append(
                (tp.matchup_num, tp.points_earned)
            )

        team_rows = []
        grand = 0.0
        for team in teams:
            pts_list = sorted(by_team.get(team.id, []))
            pts_a = pts_list[0][1] if len(pts_list) > 0 else 0
            pts_b = pts_list[1][1] if len(pts_list) > 1 else 0
            total = pts_a + pts_b
            cumulative[team.id] += total
            grand += total
            team_rows.append({
                'team': team,
                'pts_a': pts_a,
                'pts_b': pts_b,
                'total': total,
                'cumul': cumulative[team.id],
            })

        weeks_data.append({
            'week': week,
            'teams': team_rows,
            'grand_total': grand,
        })

    return weeks_data, teams


def get_weekly_prizes(season_id, week_num):
    """
    Returns the 4 prize category winners for one week, with tie handling.
    Each category: {'score': int, 'winners': [{'bowler': Bowler, 'score': int}]}
    Blinds are excluded. Only games_night1 (games 1-3) are used.
    Returns None if no entries exist.
    """
    entries = MatchupEntry.query.filter_by(
        season_id=season_id, week_num=week_num, is_blind=False
    ).all()

    candidates = []
    for e in entries:
        if not e.bowler_id or not e.games_night1:
            continue
        hcp = calculate_handicap(e.bowler_id, season_id, week_num)
        n1 = e.games_night1
        hg_s = max(n1)
        hs_s = sum(n1)
        candidates.append({
            'bowler': e.bowler,
            'hg_scratch': hg_s,
            'hg_hcp':     hg_s + hcp,
            'hs_scratch': hs_s,
            'hs_hcp':     hs_s + hcp * len(n1),
        })

    if not candidates:
        return None

    def winners(key):
        best = max(c[key] for c in candidates)
        return {
            'score': best,
            'winners': [{'bowler': c['bowler'], 'score': c[key]}
                        for c in candidates if c[key] == best],
        }

    return {
        'hg_scratch': winners('hg_scratch'),
        'hg_hcp':     winners('hg_hcp'),
        'hs_scratch': winners('hs_scratch'),
        'hs_hcp':     winners('hs_hcp'),
    }


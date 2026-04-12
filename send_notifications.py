"""
send_notifications.py — Web Push notification sender for Bowling League Tracker.

Checks three trigger conditions and fires notifications to subscribed bowlers:

  1. bowling_tomorrow — evening before each bowl date (runs ~6 PM)
  2. bowling_tonight  — morning of each bowl date (runs ~9 AM)
  3. scores_posted    — after a week's is_entered flag goes True (runs every few minutes)

Each trigger is guarded by a per-week boolean flag (notif_*_sent) so it fires exactly once.
Run via launchd; see com.dglc.bowling-notify.plist for the schedule.

Usage:
    python3 send_notifications.py [--trigger {tomorrow,tonight,scores,all}]

Default (no argument) runs all three checks.
"""

import argparse
import base64
import json
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv()

# Flask app context required for DB access
from app import create_app
app = create_app()


def _get_private_pem():
    """Decode the base64-encoded PEM private key from the environment."""
    pem_b64 = os.getenv('VAPID_PRIVATE_PEM', '')
    if not pem_b64:
        raise RuntimeError('VAPID_PRIVATE_PEM not set in environment')
    return base64.b64decode(pem_b64).decode()


def _send_push(sub, title, body, url='/m/'):
    """Send a single Web Push notification. Deletes the subscription on 410 Gone."""
    from pywebpush import webpush, WebPushException
    from models import db, PushSubscription

    claims_email = os.getenv('VAPID_CLAIMS_EMAIL', 'david@dglc.com')

    try:
        webpush(
            subscription_info=json.loads(sub.subscription_json),
            data=json.dumps({'title': title, 'body': body, 'url': url}),
            vapid_private_key=_get_private_pem(),
            vapid_claims={'sub': f'mailto:{claims_email}'},
        )
    except WebPushException as exc:
        response = exc.response
        if response is not None and response.status_code in (404, 410):
            # Subscription is gone — clean it up
            print(f'  Removing stale subscription {sub.id} (HTTP {response.status_code})')
            db.session.delete(sub)
        else:
            print(f'  Push failed for sub {sub.id}: {exc}', file=sys.stderr)


def _bowler_matchup_desc(season, week_num, team_id):
    """Return a short string like 'lanes 3-4 vs Team 2' for a bowler's matchup."""
    from models import ScheduleEntry, db
    entry = (ScheduleEntry.query
             .filter_by(season_id=season.id, week_num=week_num)
             .filter(db.or_(ScheduleEntry.team1_id == team_id,
                            ScheduleEntry.team2_id == team_id))
             .first())
    if not entry:
        return None
    opp = entry.team2 if entry.team1_id == team_id else entry.team1
    opp_name = opp.name if opp else 'TBD'
    lanes = entry.lane_pair or 'TBD'
    return f'lanes {lanes} vs {opp_name}'


def check_bowling_tomorrow():
    """Fire 'bowling tomorrow' notifications for the week that falls tomorrow."""
    from models import PushSubscription, Roster, Season, Week, db

    tomorrow = date.today() + timedelta(days=1)
    season = Season.query.filter_by(is_active=True).first()
    if not season:
        return

    week = (Week.query
            .filter_by(season_id=season.id, is_cancelled=False,
                       notif_tomorrow_sent=False)
            .filter(Week.date == tomorrow)
            .first())
    if not week:
        return

    print(f'Sending bowling_tomorrow for week {week.week_num} ({tomorrow})')
    subs = PushSubscription.query.filter_by(pref_bowling_tomorrow=True).all()
    sent = 0
    for sub in subs:
        roster = Roster.query.filter_by(bowler_id=sub.bowler_id,
                                        season_id=season.id, active=True).first()
        if not roster:
            continue
        desc = _bowler_matchup_desc(season, week.week_num, roster.team_id)
        if desc:
            body = f'Bowling tomorrow at {season.start_time}. You\'re on {desc}.'
        else:
            body = f'Bowling tomorrow at {season.start_time}.'
        _send_push(sub, 'Bowling Tomorrow 🎳', body)
        sent += 1

    week.notif_tomorrow_sent = True
    db.session.commit()
    print(f'  Sent to {sent} subscriber(s).')


def check_bowling_tonight():
    """Fire 'bowling tonight' notifications for the week that falls today."""
    from models import PushSubscription, Roster, Season, Week, db

    today = date.today()
    season = Season.query.filter_by(is_active=True).first()
    if not season:
        return

    week = (Week.query
            .filter_by(season_id=season.id, is_cancelled=False,
                       notif_tonight_sent=False)
            .filter(Week.date == today)
            .first())
    if not week:
        return

    print(f'Sending bowling_tonight for week {week.week_num} ({today})')
    subs = PushSubscription.query.filter_by(pref_bowling_tonight=True).all()
    sent = 0
    for sub in subs:
        roster = Roster.query.filter_by(bowler_id=sub.bowler_id,
                                        season_id=season.id, active=True).first()
        if not roster:
            continue
        desc = _bowler_matchup_desc(season, week.week_num, roster.team_id)
        if desc:
            body = f'Tonight at {season.start_time}. You\'re on {desc}.'
        else:
            body = f'Bowling tonight at {season.start_time}.'
        _send_push(sub, 'Bowling Tonight 🎳', body)
        sent += 1

    week.notif_tonight_sent = True
    db.session.commit()
    print(f'  Sent to {sent} subscriber(s).')


def check_scores_posted():
    """Fire 'scores posted' notifications for any week that just became entered."""
    from models import PushSubscription, Roster, ScheduleEntry, Season, TeamPoints, Week, db
    from sqlalchemy import func

    season = Season.query.filter_by(is_active=True).first()
    if not season:
        return

    # Find weeks that are entered but haven't had scores notifications sent yet
    weeks = (Week.query
             .filter_by(season_id=season.id, is_entered=True, notif_scores_sent=False)
             .all())
    if not weeks:
        return

    for week in weeks:
        print(f'Sending scores_posted for week {week.week_num}')

        # Build team standings for this week
        wk_pts = (db.session.query(TeamPoints.team_id,
                                   func.sum(TeamPoints.points_earned))
                  .filter_by(season_id=season.id, week_num=week.week_num)
                  .group_by(TeamPoints.team_id)
                  .all())
        team_totals = {tid: float(pts) for tid, pts in wk_pts}

        subs = PushSubscription.query.filter_by(pref_scores_posted=True).all()
        sent = 0
        for sub in subs:
            roster = Roster.query.filter_by(bowler_id=sub.bowler_id,
                                            season_id=season.id, active=True).first()
            if roster and team_totals:
                my_pts = team_totals.get(roster.team_id, 0)
                # Find opponent
                entry = (ScheduleEntry.query
                         .filter_by(season_id=season.id, week_num=week.week_num)
                         .filter(db.or_(ScheduleEntry.team1_id == roster.team_id,
                                        ScheduleEntry.team2_id == roster.team_id))
                         .first())
                if entry:
                    opp_id = (entry.team2_id if entry.team1_id == roster.team_id
                              else entry.team1_id)
                    opp_pts = team_totals.get(opp_id, 0)
                    if my_pts > opp_pts:
                        result = f'Your team won {my_pts:.4g}–{opp_pts:.4g}'
                    elif my_pts < opp_pts:
                        result = f'Your team lost {my_pts:.4g}–{opp_pts:.4g}'
                    else:
                        result = f'Your team tied {my_pts:.4g}–{opp_pts:.4g}'
                    body = f'Week {week.week_num} scores are in. {result}.'
                else:
                    body = f'Week {week.week_num} scores are in.'
            else:
                body = f'Week {week.week_num} scores are in.'

            _send_push(sub, 'Scores Posted 📋', body, url='/m/scores')
            sent += 1

        week.notif_scores_sent = True
        db.session.commit()
        print(f'  Sent to {sent} subscriber(s).')


def main():
    parser = argparse.ArgumentParser(description='Send bowling push notifications')
    parser.add_argument('--trigger', choices=['tomorrow', 'tonight', 'scores', 'all'],
                        default='all')
    args = parser.parse_args()

    with app.app_context():
        if args.trigger in ('tomorrow', 'all'):
            check_bowling_tomorrow()
        if args.trigger in ('tonight', 'all'):
            check_bowling_tonight()
        if args.trigger in ('scores', 'all'):
            check_scores_posted()


if __name__ == '__main__':
    main()

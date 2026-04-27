"""
check_health.py — Health check for the bowling league app.

Pings http://localhost:5001/ on each run. On first failure, emails an alert to
the admin. On recovery, emails a notice. A sentinel file at /tmp/bowling-health-down
prevents repeated alerts while the app stays down.

Install the launchd timer (run on utilityserver):

    cp ~/github/bowling-league-tracker/com.dglc.bowling-health.plist \\
       ~/Library/LaunchAgents/com.dglc.bowling-health.plist
    launchctl load ~/Library/LaunchAgents/com.dglc.bowling-health.plist
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

HEALTH_URL = 'http://localhost:5001/'
SENTINEL   = '/tmp/bowling-health-down'
TIMEOUT    = 10  # seconds
RECIPIENT  = 'david@dglc.com'


def _graph_token(tenant_id, client_id, client_secret):
    data = urllib.parse.urlencode({
        'grant_type':    'client_credentials',
        'client_id':     client_id,
        'client_secret': client_secret,
        'scope':         'https://graph.microsoft.com/.default',
    }).encode()
    req = urllib.request.Request(
        f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token',
        data=data, method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())['access_token']


def _send_email(subject, body):
    tenant_id     = os.environ['GRAPH_TENANT_ID']
    client_id     = os.environ['GRAPH_CLIENT_ID']
    client_secret = os.environ['GRAPH_CLIENT_SECRET']
    sender        = os.environ['GRAPH_SENDER_EMAIL']

    token = _graph_token(tenant_id, client_id, client_secret)
    payload = json.dumps({
        'message': {
            'subject': subject,
            'body':    {'contentType': 'HTML', 'content': body},
            'toRecipients': [{'emailAddress': {'address': RECIPIENT}}],
        },
        'saveToSentItems': True,
    }).encode()
    req = urllib.request.Request(
        f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail',
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15):
        pass  # 202 Accepted


def check():
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error = None
    try:
        urllib.request.urlopen(HEALTH_URL, timeout=TIMEOUT)
        up = True
    except urllib.error.HTTPError:
        up = True   # gunicorn is serving even if the app returns an error page
    except Exception as exc:
        up = False
        error = str(exc)

    was_down = os.path.exists(SENTINEL)

    if not up and not was_down:
        with open(SENTINEL, 'w') as f:
            f.write(now)
        try:
            _send_email(
                'mlb.dglc.com is DOWN',
                f'<p>The bowling league app did not respond at {now}.</p>'
                f'<p>Error: <code>{error}</code></p>'
                f'<p>Check <code>/tmp/bowling-app.err</code> on utilityserver.</p>',
            )
            print(f'{now} DOWN — alert sent')
        except Exception as e:
            print(f'{now} DOWN — failed to send alert: {e}', file=sys.stderr)

    elif up and was_down:
        os.remove(SENTINEL)
        try:
            _send_email(
                'mlb.dglc.com is back UP',
                f'<p>The bowling league app recovered and is responding normally at {now}.</p>',
            )
            print(f'{now} UP — recovery notice sent')
        except Exception as e:
            print(f'{now} UP — failed to send recovery notice: {e}', file=sys.stderr)

    elif not up:
        print(f'{now} still DOWN (alert already sent at {open(SENTINEL).read().strip()})')
    else:
        print(f'{now} OK')


if __name__ == '__main__':
    check()

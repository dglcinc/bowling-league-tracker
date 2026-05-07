"""
check_health.py — Health check for the bowling league app.

Runs two independent probes on each invocation:
  1. local  — http://localhost:5001/healthz (the gunicorn app on this host)
  2. public — https://mlb.dglc.com/healthz (DNS + Pi nginx + TLS + app)

Each probe has its own sentinel and alert/recovery flow, so a Pi or network
outage that leaves the local app healthy still produces a distinct alert.

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

LOCAL_URL       = 'http://localhost:5001/healthz'
PUBLIC_URL      = 'https://mlb.dglc.com/healthz'
SENTINEL_LOCAL  = '/tmp/bowling-health-down'
SENTINEL_PUBLIC = '/tmp/bowling-health-public-down'
TIMEOUT         = 10  # seconds
RECIPIENT       = 'david@dglc.com'


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


def _probe(url):
    try:
        urllib.request.urlopen(url, timeout=TIMEOUT)
        return True, None
    except urllib.error.HTTPError:
        return True, None  # something is serving even if it returns an error page
    except Exception as exc:
        return False, str(exc)


def _evaluate(label, url, sentinel, down_subject, down_body_extra, up_subject, now):
    up, error = _probe(url)
    was_down = os.path.exists(sentinel)

    if not up and not was_down:
        with open(sentinel, 'w') as f:
            f.write(now)
        try:
            _send_email(
                down_subject,
                f'<p>{label} probe failed at {now}.</p>'
                f'<p>URL: <code>{url}</code></p>'
                f'<p>Error: <code>{error}</code></p>'
                f'{down_body_extra}',
            )
            print(f'{now} {label} DOWN — alert sent')
        except Exception as e:
            print(f'{now} {label} DOWN — failed to send alert: {e}', file=sys.stderr)

    elif up and was_down:
        os.remove(sentinel)
        try:
            _send_email(
                up_subject,
                f'<p>{label} probe recovered at {now}. URL: <code>{url}</code></p>',
            )
            print(f'{now} {label} UP — recovery notice sent')
        except Exception as e:
            print(f'{now} {label} UP — failed to send recovery notice: {e}', file=sys.stderr)

    elif not up:
        print(f'{now} {label} still DOWN (alert sent at {open(sentinel).read().strip()})')
    else:
        print(f'{now} {label} OK')


def check():
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _evaluate(
        label='local',
        url=LOCAL_URL,
        sentinel=SENTINEL_LOCAL,
        down_subject='mlb.dglc.com is DOWN (local app)',
        down_body_extra='<p>Check <code>/tmp/bowling-app.err</code> on utilityserver.</p>',
        up_subject='mlb.dglc.com is back UP (local app)',
        now=now,
    )
    _evaluate(
        label='public',
        url=PUBLIC_URL,
        sentinel=SENTINEL_PUBLIC,
        down_subject='mlb.dglc.com unreachable from public internet',
        down_body_extra=(
            '<p>The local app on utilityserver may still be fine — this probe '
            'goes through DNS, the Pi at 10.0.0.82, nginx, and TLS. Likely '
            'culprit: Pi offline, network, or DNS.</p>'
        ),
        up_subject='mlb.dglc.com public URL recovered',
        now=now,
    )


if __name__ == '__main__':
    check()

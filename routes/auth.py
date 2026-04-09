"""
Authentication blueprint — login, magic link send/validate, logout.
All routes here are public (exempt from the before_request auth check in app.py).
"""

import uuid
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, current_app)
from flask_login import login_user, logout_user, current_user

from extensions import limiter
from models import db, Bowler, MagicLinkToken, LinkedAccount

auth_bp = Blueprint('auth', __name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_turnstile(cf_token):
    """Verify a Cloudflare Turnstile response server-side.
    Returns True if valid or if no secret key is configured (dev mode)."""
    secret = current_app.config.get('TURNSTILE_SECRET_KEY', '')
    if not secret:
        return True  # dev mode — skip verification
    data = urllib.parse.urlencode({
        'secret': secret,
        'response': cf_token,
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://challenges.cloudflare.com/turnstile/v1/siteverify',
        data=data, method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            return result.get('success', False)
    except Exception:
        return False


def send_magic_link(bowler):
    """Create a fresh token (invalidating all prior ones) and email the sign-in link.
    Returns (True, None) on success or (False, error_str) on failure."""
    from routes.admin import _send_via_graph

    now = datetime.utcnow()

    # Invalidate all prior unused tokens for this bowler
    MagicLinkToken.query.filter_by(
        bowler_id=bowler.id, used_at=None
    ).update({'used_at': now})

    # Create new token
    token_str = str(uuid.uuid4())
    token = MagicLinkToken(
        token=token_str,
        bowler_id=bowler.id,
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    db.session.add(token)
    db.session.commit()

    link = url_for('auth.validate_token', token=token_str, _external=True)
    name = bowler.first_name or bowler.last_name

    subject = 'Your sign-in link — League Tracker'
    html_body = f"""
<p>Hello {name},</p>
<p>Click the button below to sign in to the Bowling League Tracker.
   This link expires in 24 hours and can only be used once.</p>
<p style="margin:24px 0">
  <a href="{link}"
     style="background:#1b3a6b;color:#fff;padding:12px 24px;
            border-radius:4px;text-decoration:none;font-size:1rem">
    Sign in to League Tracker
  </a>
</p>
<p style="color:#888;font-size:0.85em">
  If you didn't request this link, you can safely ignore this email.
</p>
"""

    try:
        _send_via_graph(
            current_app.config,
            subject,
            html_body,
            to_list=[bowler.email],
            bcc_list=[],
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per 15 minutes', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        # Verify Turnstile CAPTCHA
        cf_token = request.form.get('cf-turnstile-response', '')
        if not _verify_turnstile(cf_token):
            flash('Security check failed. Please try again.', 'danger')
            return redirect(url_for('auth.login'))

        # Look up bowler by email (case-insensitive)
        bowler = Bowler.query.filter(
            db.func.lower(Bowler.email) == email
        ).first()

        if bowler:
            # Per-email cooldown: don't send if a token was issued in the last 10 minutes
            cutoff = datetime.utcnow() - timedelta(minutes=10)
            recent = MagicLinkToken.query.filter(
                MagicLinkToken.bowler_id == bowler.id,
                MagicLinkToken.created_at >= cutoff,
            ).first()
            if not recent:
                send_magic_link(bowler)

        # Always show the same message — never reveal whether email is in DB
        flash("If your email is registered, you'll receive a sign-in link shortly. "
              "Check your inbox (and spam folder).", 'info')
        return redirect(url_for('auth.login'))

    site_key = current_app.config.get('TURNSTILE_SITE_KEY', '')
    return render_template('auth/login.html', turnstile_site_key=site_key)


@auth_bp.route('/magic/<token>')
def validate_token(token):
    now = datetime.utcnow()
    tok = MagicLinkToken.query.get(token)

    if not tok or tok.used_at is not None or tok.expires_at < now:
        flash('This sign-in link is invalid or has expired. Please request a new one.',
              'danger')
        return redirect(url_for('auth.login'))

    bowler = Bowler.query.get(tok.bowler_id)
    if not bowler:
        flash('Account not found.', 'danger')
        return redirect(url_for('auth.login'))

    # Consume this token and invalidate any others for this bowler
    MagicLinkToken.query.filter_by(
        bowler_id=bowler.id, used_at=None
    ).update({'used_at': now})

    # Upsert LinkedAccount
    acct = LinkedAccount.query.filter_by(
        bowler_id=bowler.id, auth_method='magic_link'
    ).first()
    if acct:
        acct.last_login = now
    else:
        db.session.add(LinkedAccount(
            bowler_id=bowler.id,
            auth_method='magic_link',
            auth_identifier=bowler.email,
            last_login=now,
        ))

    db.session.commit()

    login_user(bowler, remember=True)
    flash(f'Welcome, {bowler.first_name or bowler.last_name}!', 'success')

    next_url = request.args.get('next', '')
    # Safety check: only redirect to relative paths
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(url_for('index'))


@auth_bp.route('/logout')
def logout():
    logout_user()
    flash('You have been signed out.', 'info')
    return redirect(url_for('auth.login'))

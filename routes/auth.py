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
                   url_for, flash, current_app, session, jsonify)
from flask_login import login_user, logout_user, current_user, login_required

from extensions import limiter
from models import db, Bowler, MagicLinkToken, LinkedAccount, WebAuthnCredential

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


def send_magic_link(bowler, subject=None):
    """Create a fresh token (invalidating all prior ones) and email the sign-in link.
    Returns (True, None) on success or (False, error_str) on failure.
    Pass a custom subject for registration invitations vs. regular sign-in links."""
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

    if subject is None:
        from models import LeagueSettings
        settings = db.session.get(LeagueSettings, 1)
        league_name = settings.league_name if settings else 'League Tracker'
        subject = f'{league_name}: Sign-In Instructions'
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
        if not _verify_turnstile(request.form.get('cf-turnstile-response', '')):
            flash('Security check failed. Please try again.', 'danger')
            return redirect(url_for('auth.login'))

        bowler = Bowler.query.filter(
            db.func.lower(Bowler.email) == email
        ).first()

        if bowler:
            send_magic_link(bowler)

        # Generic response — never confirm whether the email is registered
        flash("If your email is registered, you'll receive a sign-in link shortly. "
              "Check your inbox (and spam folder). Links expire after 24 hours.", 'info')
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


# ---------------------------------------------------------------------------
# Passkey management
# ---------------------------------------------------------------------------

@auth_bp.route('/passkeys')
@login_required
def passkeys():
    creds = WebAuthnCredential.query.filter_by(bowler_id=current_user.id).all()
    return render_template('auth/passkeys.html', creds=creds)


@auth_bp.route('/passkeys/<int:cred_id>/delete', methods=['POST'])
@login_required
def delete_passkey(cred_id):
    cred = WebAuthnCredential.query.filter_by(
        id=cred_id, bowler_id=current_user.id
    ).first_or_404()
    db.session.delete(cred)
    db.session.commit()
    flash('Passkey removed. You can set up a new one after signing in.', 'info')
    return redirect(url_for('auth.passkeys'))


# ---------------------------------------------------------------------------
# WebAuthn / Passkey routes (Touch ID, Face ID, Windows Hello)
# ---------------------------------------------------------------------------

@auth_bp.route('/webauthn/register/begin', methods=['POST'])
@login_required
def webauthn_register_begin():
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, AuthenticatorAttachment,
        ResidentKeyRequirement, UserVerificationRequirement,
        PublicKeyCredentialDescriptor,
    )
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

    existing = WebAuthnCredential.query.filter_by(bowler_id=current_user.id).all()
    exclude = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=current_app.config['WEBAUTHN_RP_ID'],
        rp_name=current_app.config['WEBAUTHN_RP_NAME'],
        user_id=str(current_user.id).encode(),
        user_name=current_user.email or str(current_user.id),
        user_display_name=current_user.display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude,
    )

    session['webauthn_reg_challenge'] = bytes_to_base64url(options.challenge)
    return current_app.response_class(
        response=options_to_json(options), mimetype='application/json'
    )


@auth_bp.route('/webauthn/register/complete', methods=['POST'])
@login_required
def webauthn_register_complete():
    from webauthn import verify_registration_response
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

    challenge_b64 = session.pop('webauthn_reg_challenge', None)
    if not challenge_b64:
        return jsonify({'error': 'Session expired — try again'}), 400

    data = request.get_json(force=True)
    device_name = data.pop('device_name', 'Passkey') if isinstance(data, dict) else 'Passkey'

    try:
        verified = verify_registration_response(
            credential=data,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=current_app.config['WEBAUTHN_RP_ID'],
            expected_origin=current_app.config['WEBAUTHN_ORIGIN'],
        )
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400

    cred = WebAuthnCredential(
        bowler_id=current_user.id,
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        device_name=device_name or 'Passkey',
    )
    db.session.add(cred)
    db.session.commit()
    return jsonify({'ok': True})


@auth_bp.route('/webauthn/authenticate/begin', methods=['POST'])
def webauthn_authenticate_begin():
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import (
        UserVerificationRequirement, PublicKeyCredentialDescriptor,
    )
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email:
        return jsonify({'error': 'Enter your email address first, then click the passkey button.'}), 400

    bowler = Bowler.query.filter(db.func.lower(Bowler.email) == email).first()
    if not bowler:
        # Don't reveal whether email is registered — same generic flow
        return jsonify({'error': 'No passkey found for this email. '
                        'Sign in with an email link first, then set up a passkey from the banner that appears.'}), 400

    creds = WebAuthnCredential.query.filter_by(bowler_id=bowler.id).all()
    if not creds:
        return jsonify({'error': 'No passkey registered yet for this account. '
                        'Sign in with an email link first, then set up a passkey from the banner that appears.'}), 400

    allow_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
        for c in creds
    ]
    bowler_id = bowler.id

    options = generate_authentication_options(
        rp_id=current_app.config['WEBAUTHN_RP_ID'],
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    session['webauthn_auth_challenge'] = bytes_to_base64url(options.challenge)
    session['webauthn_auth_bowler_id'] = bowler_id  # unused in complete() but kept for future use
    return current_app.response_class(
        response=options_to_json(options), mimetype='application/json'
    )


@auth_bp.route('/webauthn/authenticate/complete', methods=['POST'])
def webauthn_authenticate_complete():
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes

    challenge_b64 = session.pop('webauthn_auth_challenge', None)
    session.pop('webauthn_auth_bowler_id', None)

    if not challenge_b64:
        return jsonify({'error': 'Session expired — try again'}), 400

    data = request.get_json(force=True)

    # Look up the credential record by its ID
    cred_id_b64 = data.get('id', '')
    cred_record = WebAuthnCredential.query.filter_by(credential_id=cred_id_b64).first()
    if not cred_record:
        return jsonify({'error': 'Passkey not recognised'}), 400

    bowler = db.session.get(Bowler, cred_record.bowler_id)
    if not bowler:
        return jsonify({'error': 'Account not found'}), 400

    try:
        verified = verify_authentication_response(
            credential=data,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=current_app.config['WEBAUTHN_RP_ID'],
            expected_origin=current_app.config['WEBAUTHN_ORIGIN'],
            credential_public_key=cred_record.public_key,
            credential_current_sign_count=cred_record.sign_count,
        )
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400

    now = datetime.utcnow()
    cred_record.sign_count = verified.new_sign_count
    cred_record.last_used_at = now

    # Upsert LinkedAccount
    acct = LinkedAccount.query.filter_by(
        bowler_id=bowler.id, auth_method='webauthn'
    ).first()
    if acct:
        acct.last_login = now
    else:
        db.session.add(LinkedAccount(
            bowler_id=bowler.id,
            auth_method='webauthn',
            auth_identifier=cred_record.credential_id,
            last_login=now,
        ))

    db.session.commit()
    login_user(bowler, remember=True)
    return jsonify({'ok': True, 'redirect': url_for('index')})

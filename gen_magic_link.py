"""
Emergency / bootstrap magic link generator.
Run from the terminal to get a sign-in URL without email.

Usage:
    python gen_magic_link.py            # generates link for bowler id=34 (David Lewis)
    python gen_magic_link.py <id>       # generates link for any bowler by id

Paste the printed URL into your browser. The app does not need to be running
when you run this script, but it must be running when you visit the URL.
"""

import sys
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from models import db, Bowler, MagicLinkToken

bowler_id = int(sys.argv[1]) if len(sys.argv) > 1 else 34

app = create_app()
with app.app_context():
    bowler = db.session.get(Bowler, bowler_id)
    if not bowler:
        print(f'No bowler found with id={bowler_id}')
        sys.exit(1)

    now = datetime.utcnow()
    # Invalidate any existing unused tokens
    MagicLinkToken.query.filter_by(bowler_id=bowler.id, used_at=None).update({'used_at': now})

    token_str = str(uuid.uuid4())
    db.session.add(MagicLinkToken(
        token=token_str,
        bowler_id=bowler.id,
        expires_at=now + timedelta(hours=24),
        created_at=now,
    ))
    db.session.commit()

    print(f'\nSign-in link for {bowler.display_name}:')
    print(f'\n    http://localhost:5001/auth/magic/{token_str}\n')
    print('Paste this URL into your browser. Expires in 24 hours.\n')

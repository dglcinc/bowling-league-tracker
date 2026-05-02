"""
Shared Flask extensions — imported by both app.py and blueprints to avoid circular imports.
"""

from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'warning'

# In-memory rate limiting. Each gunicorn worker keeps its own counter, so the
# effective limit per IP is roughly (configured_limit × num_workers). At 2
# workers and limits like '5 per 15 minutes', the worst case is ~10/15min per
# IP — still tight enough for our use. Explicit storage_uri silences the
# flask-limiter "no storage was specified" warning at boot.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)

# In-process SimpleCache — no Redis needed; busted explicitly after score entry
cache = Cache()

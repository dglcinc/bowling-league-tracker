"""
Shared Flask extensions — imported by both app.py and blueprints to avoid circular imports.
"""

from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

login_manager = LoginManager()
login_manager.login_message_category = 'warning'

# In-memory rate limiting (single process, no Redis needed at this scale)
limiter = Limiter(key_func=get_remote_address, default_limits=[])

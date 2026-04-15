"""
SQLAlchemy models for Bowling League Tracker.
All stats are computed on the fly from matchup_entries — nothing derived is stored.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class Bowler(UserMixin, db.Model):
    """A person who has ever bowled in the league. Never deleted."""
    __tablename__ = 'bowlers'

    id = db.Column(db.Integer, primary_key=True)
    last_name = db.Column(db.String(64), nullable=False)
    first_name = db.Column(db.String(64))
    nickname = db.Column(db.String(64))
    email = db.Column(db.String(128))
    is_editor = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    roster_entries = db.relationship('Roster', back_populates='bowler', lazy='dynamic')

    @property
    def display_name(self):
        return f"{self.last_name}, {self.first_name}" if self.first_name else self.last_name

    def short_name(self, use_nickname=False):
        """Last name only, or nickname if available and use_nickname is True."""
        if use_nickname and self.nickname:
            return self.nickname
        return self.last_name

    def __repr__(self):
        return f'<Bowler {self.last_name}>'


_DEFAULT_INVITE_MESSAGE = (
    "Please visit https://mlb.dglc.com to access the bowling app for the league and request a "
    "one-time password to log in. It will run on your Apple or Android device, or your computer. "
    "Use on your phone for quick information. Use on your tablet or computer for full stats and "
    "history. The mobile version can be added to your home screen for easy access. Once you have "
    "entered a one-time password, it will stay active for 90 days. You can set up a passkey or "
    "touch/face id. On Apple, you must add the icon to your home screen first. You can access the "
    "full app on your phone by following the link for that, but it will be a little tricky to "
    "navigate on your phone. Enjoy!"
)


class LeagueSettings(db.Model):
    """Global league-level settings (single row, id=1)."""
    __tablename__ = 'league_settings'

    id = db.Column(db.Integer, primary_key=True)
    league_name = db.Column(db.String(128), default='Mountain Lakes Men\'s Bowling League')
    use_nickname = db.Column(db.Boolean, default=False)
    show_captain_name = db.Column(db.Boolean, default=False)
    invite_message = db.Column(db.Text)


class Season(db.Model):
    """One bowling season (e.g. 2025-2026)."""
    __tablename__ = 'seasons'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False, unique=True)  # e.g. "2025-2026"
    start_date = db.Column(db.Date)
    num_weeks = db.Column(db.Integer, default=23)
    half_boundary_week = db.Column(db.Integer, default=11)  # last week of first half
    handicap_base = db.Column(db.Integer, default=200)
    handicap_factor = db.Column(db.Float, default=0.9)
    blind_scratch = db.Column(db.Integer, default=125)
    blind_handicap = db.Column(db.Integer, default=60)
    is_active = db.Column(db.Boolean, default=True)
    bowling_format = db.Column(db.String(10), default='single')  # 'single' or 'double'
    venue = db.Column(db.String(32), default='boonton_lanes')   # 'mountain_lakes_club' or 'boonton_lanes'
    arrival_time = db.Column(db.String(16), default='7:45 PM')
    start_time = db.Column(db.String(16), default='8:00 PM')
    home_message = db.Column(db.Text, nullable=True)

    # Configurable display names for the 4 post-season tournament weeks.
    # These are stored in the DB so personal names never appear in the repo.
    name_club_championship = db.Column(db.String(128), default='Club Championship')
    name_indiv_scratch     = db.Column(db.String(128), default='Harry E. Russell Championship')
    name_indiv_hcp_1       = db.Column(db.String(128), default='Chad Harris Memorial Bowl')
    name_indiv_hcp_2       = db.Column(db.String(128), default='Shep Belyea Open')

    @property
    def tournament_labels(self):
        """Map tournament_type key → display name for this season."""
        return {
            'club_championship': self.name_club_championship or 'Club Championship',
            'indiv_scratch':     self.name_indiv_scratch     or 'Individual Scratch Championship',
            'indiv_hcp_1':       self.name_indiv_hcp_1       or 'Individual Handicap Tournament 1',
            'indiv_hcp_2':       self.name_indiv_hcp_2       or 'Individual Handicap Tournament 2',
        }

    teams = db.relationship('Team', back_populates='season', lazy='dynamic')
    roster = db.relationship('Roster', back_populates='season', lazy='dynamic')
    weeks = db.relationship('Week', back_populates='season', lazy='dynamic', order_by='Week.week_num')
    schedule = db.relationship('ScheduleEntry', back_populates='season', lazy='dynamic')

    def __repr__(self):
        return f'<Season {self.name}>'


class Team(db.Model):
    """A team within a season."""
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    number = db.Column(db.Integer, nullable=False)   # 1–4
    name = db.Column(db.String(64), nullable=False)   # e.g. "Team 1" or a chosen team name
    captain_name = db.Column(db.String(64))           # e.g. "Lewis"

    season = db.relationship('Season', back_populates='teams')
    roster = db.relationship('Roster', back_populates='team', lazy='dynamic')

    def __repr__(self):
        return f'<Team {self.number} {self.name}>'


class Roster(db.Model):
    """A bowler's participation record for one season."""
    __tablename__ = 'roster'
    __table_args__ = (
        db.UniqueConstraint('bowler_id', 'season_id', name='uq_bowler_season'),
    )

    id = db.Column(db.Integer, primary_key=True)
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    active = db.Column(db.Boolean, default=True)
    prior_handicap = db.Column(db.Integer, default=0)  # carried from prior season end
    joined_week = db.Column(db.Integer, default=1)      # for mid-season additions

    bowler = db.relationship('Bowler', back_populates='roster_entries')
    season = db.relationship('Season', back_populates='roster')
    team = db.relationship('Team', back_populates='roster')

    def __repr__(self):
        return f'<Roster bowler={self.bowler_id} season={self.season_id}>'


class Week(db.Model):
    """One night of bowling in a season."""
    __tablename__ = 'weeks'
    __table_args__ = (
        db.UniqueConstraint('season_id', 'week_num', name='uq_season_week'),
    )

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date)
    is_position_night = db.Column(db.Boolean, default=False)
    is_cancelled = db.Column(db.Boolean, default=False)
    notes = db.Column(db.String(256))
    is_entered = db.Column(db.Boolean, default=False)  # scores have been entered
    tournament_type = db.Column(db.String(32), nullable=True)  # None = regular week; else tournament name
    # Notification-sent flags — set True after each notification type fires to prevent duplicates
    notif_tomorrow_sent = db.Column(db.Boolean, default=False)
    notif_tonight_sent = db.Column(db.Boolean, default=False)
    notif_scores_sent = db.Column(db.Boolean, default=False)

    season = db.relationship('Season', back_populates='weeks')

    def __repr__(self):
        return f'<Week {self.week_num} season={self.season_id}>'


class ScheduleEntry(db.Model):
    """Which teams play which other teams on which lane pair each week."""
    __tablename__ = 'schedule'
    __table_args__ = (
        db.UniqueConstraint('season_id', 'week_num', 'matchup_num', name='uq_matchup'),
    )

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    matchup_num = db.Column(db.Integer, nullable=False)  # 1–4
    team1_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    team2_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    lane_pair = db.Column(db.String(8))  # e.g. "1-2"

    season = db.relationship('Season', back_populates='schedule')
    team1 = db.relationship('Team', foreign_keys=[team1_id])
    team2 = db.relationship('Team', foreign_keys=[team2_id])

    def __repr__(self):
        return f'<ScheduleEntry week={self.week_num} matchup={self.matchup_num}>'


class MatchupEntry(db.Model):
    """
    One bowler's (or blind's) scores for one matchup in one week.
    A null bowler_id with is_blind=True means a blind entry.
    lane_side 'A' or 'B' tracks which side of the lane pair they bowled on.
    """
    __tablename__ = 'matchup_entries'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    matchup_num = db.Column(db.Integer, nullable=False)  # 1–4
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=True)
    is_blind = db.Column(db.Boolean, default=False)
    lane_side = db.Column(db.String(1))  # 'A' or 'B'

    # Games 1–3: primary (single night). Games 4–6: second session (legacy double-night).
    game1 = db.Column(db.Integer)
    game2 = db.Column(db.Integer)
    game3 = db.Column(db.Integer)
    game4 = db.Column(db.Integer)
    game5 = db.Column(db.Integer)
    game6 = db.Column(db.Integer)

    team = db.relationship('Team')
    bowler = db.relationship('Bowler')

    @property
    def games_night1(self):
        return [g for g in [self.game1, self.game2, self.game3] if g is not None]

    @property
    def games_night2(self):
        return [g for g in [self.game4, self.game5, self.game6] if g is not None]

    @property
    def all_games(self):
        return self.games_night1 + self.games_night2

    @property
    def total_pins(self):
        return sum(self.all_games)

    @property
    def game_count(self):
        return len(self.all_games)

    def __repr__(self):
        return f'<MatchupEntry week={self.week_num} bowler={self.bowler_id}>'


class TeamPoints(db.Model):
    """Points earned by a team in one matchup."""
    __tablename__ = 'team_points'
    __table_args__ = (
        db.UniqueConstraint('season_id', 'week_num', 'matchup_num', 'team_id',
                            name='uq_team_points'),
    )

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    matchup_num = db.Column(db.Integer, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    points_earned = db.Column(db.Float, default=0)  # Float to handle 0.5-pt ties
    is_forfeit = db.Column(db.Boolean, default=False)

    team = db.relationship('Team')

    def __repr__(self):
        return f'<TeamPoints week={self.week_num} team={self.team_id} pts={self.points_earned}>'


class TournamentEntry(db.Model):
    """
    One bowler's (or write-in's) scores for a tournament week.
    Used for indiv_scratch (5 games) and indiv_hcp_1/indiv_hcp_2 (3 games hcp).
    Write-in participants have bowler_id=None and guest_name set.
    """
    __tablename__ = 'tournament_entries'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=True)
    guest_name = db.Column(db.String(128), nullable=True)  # write-in participant
    game1 = db.Column(db.Integer)
    game2 = db.Column(db.Integer)
    game3 = db.Column(db.Integer)
    game4 = db.Column(db.Integer)
    game5 = db.Column(db.Integer)
    handicap = db.Column(db.Integer, default=0)
    place = db.Column(db.Integer, nullable=True)  # 1/2/3 for historical imports; None if unranked

    bowler = db.relationship('Bowler')

    @property
    def display_name(self):
        if self.guest_name:
            return self.guest_name
        return self.bowler.display_name if self.bowler else '(unknown)'

    @property
    def games(self):
        return [g for g in [self.game1, self.game2, self.game3, self.game4, self.game5]
                if g is not None]

    @property
    def total_scratch(self):
        return sum(self.games)

    @property
    def total_with_hcp(self):
        return self.total_scratch + self.handicap * len(self.games)

    def __repr__(self):
        return f'<TournamentEntry week={self.week_num} bowler={self.bowler_id}>'


class PayoutConfig(db.Model):
    """End-of-season payout configuration for one season."""
    __tablename__ = 'payout_configs'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False, unique=True)
    total_available = db.Column(db.Float, default=0.0)
    tournament_prize_1 = db.Column(db.Float, default=125.0)
    tournament_prize_2 = db.Column(db.Float, default=100.0)
    tournament_prize_3 = db.Column(db.Float, default=75.0)
    weekly_win_rate = db.Column(db.Float, default=10.0)
    ytd_prize_rate = db.Column(db.Float, default=75.0)
    trophy_cost = db.Column(db.Float, default=125.0)
    # Legacy single-pool percentages (kept for migration safety, no longer used)
    team_pct_json = db.Column(db.Text, default='[40, 30, 20, 10]')
    final_week = db.Column(db.Integer, default=22)
    # Three-award team payout structure
    team_award_pcts_json = db.Column(db.Text, default='[40, 40, 20]')
    team_place_pcts_json = db.Column(db.Text, default='[[35,25,20,20],[35,25,20,20],[60,40]]')
    championship_start_week = db.Column(db.Integer, default=20)

    season = db.relationship('Season')

    def __repr__(self):
        return f'<PayoutConfig season={self.season_id}>'


class LinkedAccount(db.Model):
    """Tracks how a bowler has authenticated (magic link, Google, etc.)."""
    __tablename__ = 'linked_accounts'

    id = db.Column(db.Integer, primary_key=True)
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=False)
    auth_method = db.Column(db.String(32), nullable=False)  # 'magic_link', 'google'
    auth_identifier = db.Column(db.String(256))             # email or OAuth sub
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bowler = db.relationship('Bowler')

    def __repr__(self):
        return f'<LinkedAccount bowler={self.bowler_id} method={self.auth_method}>'


class LoginOtp(db.Model):
    """Short-lived 6-digit code sent by email — replaces magic links for day-to-day login."""
    __tablename__ = 'login_otps'

    id = db.Column(db.Integer, primary_key=True)
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bowler = db.relationship('Bowler')

    def __repr__(self):
        return f'<LoginOtp bowler={self.bowler_id} used={self.used_at is not None}>'


class MagicLinkToken(db.Model):
    """Single-use sign-in tokens sent via email."""
    __tablename__ = 'magic_link_tokens'

    token = db.Column(db.String(36), primary_key=True)  # UUID4 string
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bowler = db.relationship('Bowler')

    def __repr__(self):
        return f'<MagicLinkToken bowler={self.bowler_id} used={self.used_at is not None}>'


class ViewerPermission(db.Model):
    """Controls which Flask endpoints non-editor (viewer) users may access."""
    __tablename__ = 'viewer_permissions'

    endpoint = db.Column(db.String(128), primary_key=True)  # Flask endpoint name
    label = db.Column(db.String(128), nullable=False)
    viewer_accessible = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<ViewerPermission {self.endpoint} accessible={self.viewer_accessible}>'


class WebAuthnCredential(db.Model):
    """Passkey / platform authenticator credential for Touch ID, Face ID, etc."""
    __tablename__ = 'webauthn_credentials'

    id = db.Column(db.Integer, primary_key=True)
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=False)
    credential_id = db.Column(db.String(512), nullable=False, unique=True)  # base64url-encoded
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.Integer, default=0)
    device_name = db.Column(db.String(128), default='Passkey')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)

    bowler = db.relationship('Bowler')

    def __repr__(self):
        return f'<WebAuthnCredential bowler={self.bowler_id} device={self.device_name}>'


class PushSubscription(db.Model):
    """Web Push subscription for one browser/device belonging to a bowler."""
    __tablename__ = 'push_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    bowler_id = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=False)
    # The endpoint URL uniquely identifies a subscription; used for upsert
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    # Full JSON blob from browser (endpoint + keys.p256dh + keys.auth)
    subscription_json = db.Column(db.Text, nullable=False)
    platform = db.Column(db.String(32))  # 'ios', 'android', 'desktop'
    # Per-subscription notification preferences
    pref_bowling_tomorrow = db.Column(db.Boolean, default=True)
    pref_bowling_tonight = db.Column(db.Boolean, default=True)
    pref_scores_posted = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bowler = db.relationship('Bowler')

    def __repr__(self):
        return f'<PushSubscription bowler={self.bowler_id} platform={self.platform}>'


class ClubChampionshipResult(db.Model):
    """
    Records team placements for the Club Championship (post-season week 23).
    Determined by total wood in a first-half vs second-half bracket — not
    computable from regular-season points, so must be entered manually.
    """
    __tablename__ = 'club_championship_results'

    id       = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    team_id  = db.Column(db.Integer, db.ForeignKey('teams.id'),   nullable=False)
    place    = db.Column(db.Integer, nullable=False)  # 1 / 2 / 3 / 4

    team = db.relationship('Team')

    def __repr__(self):
        return f'<ClubChampionshipResult season={self.season_id} place={self.place} team={self.team_id}>'


class Snapshot(db.Model):
    """Weekly JSON snapshot of all stats, auto-saved after entry."""
    __tablename__ = 'snapshots'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('seasons.id'), nullable=False)
    week_num = db.Column(db.Integer, nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Snapshot season={self.season_id} week={self.week_num}>'


class RequestLog(db.Model):
    """Per-request access log stored in the DB for the activity dashboard."""
    __tablename__ = 'request_log'

    id          = db.Column(db.Integer, primary_key=True)
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    bowler_id   = db.Column(db.Integer, db.ForeignKey('bowlers.id'), nullable=True)
    endpoint    = db.Column(db.String(128))
    path        = db.Column(db.String(512))
    method      = db.Column(db.String(8))
    status_code = db.Column(db.Integer, index=True)
    remote_addr = db.Column(db.String(45))
    user_agent  = db.Column(db.String(256))

    bowler = db.relationship('Bowler', foreign_keys=[bowler_id])

    def __repr__(self):
        return f'<RequestLog {self.method} {self.path} {self.status_code}>'

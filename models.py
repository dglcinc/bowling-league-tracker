"""
SQLAlchemy models for Bowling League Tracker.
All stats are computed on the fly from matchup_entries — nothing derived is stored.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Bowler(db.Model):
    """A person who has ever bowled in the league. Never deleted."""
    __tablename__ = 'bowlers'

    id = db.Column(db.Integer, primary_key=True)
    last_name = db.Column(db.String(64), nullable=False)
    first_name = db.Column(db.String(64))
    nickname = db.Column(db.String(64))
    email = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    roster_entries = db.relationship('Roster', back_populates='bowler', lazy='dynamic')

    @property
    def display_name(self):
        return f"{self.last_name}, {self.first_name}" if self.first_name else self.last_name

    def __repr__(self):
        return f'<Bowler {self.last_name}>'


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
    name = db.Column(db.String(64), nullable=False)  # e.g. "Lewis"

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
    team1_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team2_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
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

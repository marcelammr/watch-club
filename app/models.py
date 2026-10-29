from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    username: Mapped[str] = mapped_column(String(80), nullable=False, default="user")
    username_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    pending_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    avatar: Mapped[str] = mapped_column(String(40), default="popcorn", nullable=False)
    avatar_type: Mapped[str] = mapped_column(String(16), default="illustrated", nullable=False)
    avatar_provider: Mapped[str] = mapped_column(String(32), default="watchclub", nullable=False)
    avatar_value: Mapped[str] = mapped_column(String(120), default="popcorn", nullable=False)
    bio: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    google_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    facebook_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    presence: Mapped[str] = mapped_column(String(12), default="offline", nullable=False)
    presence_pref: Mapped[str] = mapped_column(String(12), default="auto", nullable=False)
    displayed_club_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    memberships: Mapped[list["ClubMember"]] = relationship(back_populates="user")
    email_tokens: Mapped[list["EmailToken"]] = relationship(back_populates="user")
    messages: Mapped[list["ClubMessage"]] = relationship(back_populates="user")


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(20), default="activate", nullable=False)
    new_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="email_tokens")


class AccountInvite(Base):
    __tablename__ = "account_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Club(Base):
    __tablename__ = "clubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    join_code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_closed: Mapped[bool] = mapped_column(default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rules: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cover_color: Mapped[str] = mapped_column(String(7), default="#3a2348", nullable=False)
    cover_image: Mapped[str | None] = mapped_column(String(120), nullable=True)
    icon_image: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tag_slug: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    tag_emoji: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # legado: token antigo (lavender, …). Não é lido nem escrito pelo código novo; remover depois.
    tag_color: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    tag_color_mode: Mapped[str] = mapped_column(String(8), default="solid", nullable=False)
    tag_color_1: Mapped[str] = mapped_column(String(7), default="#B892FF", nullable=False)
    tag_color_2: Mapped[str | None] = mapped_column(String(7), nullable=True)
    tag_gradient_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tag_bg_intensity: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    tag_border_intensity: Mapped[int] = mapped_column(Integer, default=55, nullable=False)
    tag_emoji_position: Mapped[str] = mapped_column(String(8), default="start", nullable=False)
    admin_name_color: Mapped[str] = mapped_column(String(7), default="#B892FF", nullable=False)
    sub_name_color: Mapped[str] = mapped_column(String(7), default="#6C63FF", nullable=False)
    member_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["ClubMember"]] = relationship(back_populates="club")
    shows: Mapped[list["ClubShow"]] = relationship(back_populates="club")
    watch_rounds: Mapped[list["ClubWatchRound"]] = relationship(
        back_populates="club", cascade="all, delete-orphan"
    )
    schedules: Mapped[list["ClubSchedule"]] = relationship(back_populates="club")
    messages: Mapped[list["ClubMessage"]] = relationship(back_populates="club")
    catalog_categories: Mapped[list["ClubCatalogCategory"]] = relationship(back_populates="club")
    content_tags: Mapped[list["ClubContentTag"]] = relationship(back_populates="club")


class ClubMember(Base):
    __tablename__ = "club_members"
    __table_args__ = (UniqueConstraint("club_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    support_perms: Mapped[str] = mapped_column(Text, default="", nullable=False)

    club: Mapped[Club] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class ClubJoinRequest(Base):
    __tablename__ = "club_join_requests"
    __table_args__ = (UniqueConstraint("club_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()


class Show(Base):
    __tablename__ = "shows"
    __table_args__ = (
        Index("ix_shows_tmdb_id", "tmdb_id", unique=True),
        Index("ix_shows_imdb_id", "imdb_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tvmaze_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="serie", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    premiered: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    backdrop_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    official_site: Mapped[str | None] = mapped_column(String(500), nullable=True)
    genres: Mapped[str | None] = mapped_column(Text, nullable=True)
    news_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    seasons: Mapped[list["Season"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    news: Mapped[list["NewsItem"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    clubs: Mapped[list["ClubShow"]] = relationship(back_populates="show")


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("show_id", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    episode_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    premiere_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    show: Mapped[Show] = relationship(back_populates="seasons")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="season")


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (Index("ix_episodes_show_season_number", "show_id", "season_number", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False, index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), nullable=True)
    tvmaze_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    airdate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    show: Mapped[Show] = relationship(back_populates="episodes")
    season: Mapped[Season | None] = relationship(back_populates="episodes")


class ClubShow(Base):
    __tablename__ = "club_shows"
    __table_args__ = (UniqueConstraint("club_id", "show_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    added_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    watch_status: Mapped[str] = mapped_column(String(20), default="watching", nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    club: Mapped[Club] = relationship(back_populates="shows")
    show: Mapped[Show] = relationship(back_populates="clubs")


class ClubWatchRound(Base):
    __tablename__ = "club_watch_rounds"
    __table_args__ = (
        UniqueConstraint("club_id", "show_id", "number"),
        Index("ix_club_watch_rounds_club_show", "club_id", "show_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    club: Mapped[Club] = relationship(back_populates="watch_rounds")
    show: Mapped[Show] = relationship()
    watches: Mapped[list["ClubEpisodeWatch"]] = relationship(
        back_populates="round", cascade="all, delete-orphan"
    )


class ClubEpisodeWatch(Base):
    __tablename__ = "club_episode_watches"
    __table_args__ = (UniqueConstraint("round_id", "episode_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("club_watch_rounds.id"), nullable=False, index=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    watched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    marked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    round: Mapped[ClubWatchRound] = relationship(back_populates="watches")
    episode: Mapped[Episode] = relationship()
    marked_by: Mapped[User | None] = relationship()


class ClubSchedule(Base):
    __tablename__ = "club_schedules"
    __table_args__ = (Index("ix_club_schedules_club_starts", "club_id", "starts_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False, index=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    club: Mapped[Club] = relationship(back_populates="schedules")
    show: Mapped[Show] = relationship()
    created_by: Mapped[User] = relationship()


class ClubShowRating(Base):
    __tablename__ = "club_show_ratings"
    __table_args__ = (UniqueConstraint("club_id", "user_id", "show_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ClubMessage(Base):
    __tablename__ = "club_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    club: Mapped[Club] = relationship(back_populates="messages")
    user: Mapped[User] = relationship(back_populates="messages")


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (UniqueConstraint("user_low_id", "user_high_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_low_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    user_high_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DirectMessage(Base):
    __tablename__ = "direct_messages"
    __table_args__ = (Index("ix_dm_pair", "sender_id", "recipient_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sender: Mapped[User] = relationship(foreign_keys=[sender_id])


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(800), nullable=False)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(80), nullable=True)

    show: Mapped[Show] = relationship(back_populates="news")


class CatalogCategory(Base):
    __tablename__ = "catalog_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    clubs: Mapped[list["ClubCatalogCategory"]] = relationship(back_populates="category")


class ClubCatalogCategory(Base):
    __tablename__ = "club_catalog_categories"
    __table_args__ = (UniqueConstraint("club_id", "category_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("catalog_categories.id"), nullable=False, index=True)

    club: Mapped[Club] = relationship(back_populates="catalog_categories")
    category: Mapped[CatalogCategory] = relationship(back_populates="clubs")


class ContentTag(Base):
    __tablename__ = "content_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)

    clubs: Mapped[list["ClubContentTag"]] = relationship(back_populates="tag")


class ClubContentTag(Base):
    __tablename__ = "club_content_tags"
    __table_args__ = (UniqueConstraint("club_id", "tag_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("content_tags.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    club: Mapped[Club] = relationship(back_populates="content_tags")
    tag: Mapped[ContentTag] = relationship(back_populates="clubs")

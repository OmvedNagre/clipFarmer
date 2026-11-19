from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PlatformSource(Entity, Base):
    __tablename__ = "platform_sources"
    platform: Mapped[str] = mapped_column(String(24), unique=True)
    display_name: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40), default="not_configured")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class DiscoverySearch(Entity, Base):
    __tablename__ = "discovery_searches"
    query: Mapped[str] = mapped_column(String(200))
    platforms: Mapped[list] = mapped_column(JSON)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="running")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DiscoveredItem(Entity, Base):
    __tablename__ = "discovered_items"
    __table_args__ = (UniqueConstraint("platform", "external_id"),)
    platform: Mapped[str] = mapped_column(String(24), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    canonical_url: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    creator_id: Mapped[str | None] = mapped_column(String(128))
    creator_name: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(Integer)
    like_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    media_access_type: Mapped[str] = mapped_column(String(40), default="metadata_only")
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    discovery_search_id: Mapped[str | None] = mapped_column(
        ForeignKey("discovery_searches.id"), index=True
    )
    saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class SearchResult(Base):
    __tablename__ = "search_results"
    search_id: Mapped[str] = mapped_column(ForeignKey("discovery_searches.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("discovered_items.id"), primary_key=True, index=True
    )


class MediaAsset(Entity, Base):
    __tablename__ = "media_assets"
    discovered_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("discovered_items.id"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(240))
    stored_filename: Mapped[str] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    duration_seconds: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    video_codec: Mapped[str] = mapped_column(String(40))
    audio_codec: Mapped[str | None] = mapped_column(String(40))
    authorization_status: Mapped[str] = mapped_column(String(40), index=True)
    authorization_notes: Mapped[str] = mapped_column(Text, default="")
    source_provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    publishing_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    subtitle_srt: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class ProcessingJob(Entity, Base):
    __tablename__ = "processing_jobs"
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    options: Mapped[dict] = mapped_column(JSON)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class JobEvent(Entity, Base):
    __tablename__ = "job_events"
    processing_job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)


class VideoOutput(Entity, Base):
    __tablename__ = "video_outputs"
    processing_job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    profile: Mapped[str] = mapped_column(String(40))
    storage_path: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(150))
    mime_type: Mapped[str] = mapped_column(String(80), default="video/mp4")
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    video_codec: Mapped[str] = mapped_column(String(40))
    audio_codec: Mapped[str | None] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    validation_status: Mapped[str] = mapped_column(String(30), default="verified")
    subtitle_srt: Mapped[str] = mapped_column(Text, default="")


class ReviewAction(Entity, Base):
    __tablename__ = "review_actions"
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str] = mapped_column(Text, default="")


class DeliveryRecord(Entity, Base):
    __tablename__ = "delivery_records"
    video_output_id: Mapped[str] = mapped_column(ForeignKey("video_outputs.id"), index=True)
    destination: Mapped[str] = mapped_column(String(30), default="telegram")
    status: Mapped[str] = mapped_column(String(30))
    external_message_id: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class WatchSession(Entity, Base):
    __tablename__ = "watch_sessions"
    platform: Mapped[str] = mapped_column(String(20))
    source_url: Mapped[str] = mapped_column(Text)
    creator_id: Mapped[str] = mapped_column(String(128))
    creator_name: Mapped[str] = mapped_column(String(200))
    authorization_notes: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[dict] = mapped_column(JSON)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    diagnostic: Mapped[str] = mapped_column(Text, default="Waiting for watcher worker")
    chat_buckets: Mapped[list] = mapped_column(JSON, default=list)
    reconnects: Mapped[int] = mapped_column(Integer, default=0)


class WatchMoment(Entity, Base):
    __tablename__ = "watch_moments"
    watch_session_id: Mapped[str] = mapped_column(ForeignKey("watch_sessions.id"), index=True)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    media_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"))
    processing_job_id: Mapped[str | None] = mapped_column(ForeignKey("processing_jobs.id"))


class DiscoverySchedule(Entity, Base):
    __tablename__ = "discovery_schedules"
    query: Mapped[str] = mapped_column(String(200))
    platforms: Mapped[list] = mapped_column(JSON)
    creator_ids: Mapped[list] = mapped_column(JSON)
    interval_minutes: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    diagnostic: Mapped[str] = mapped_column(Text, default="Waiting for scheduler")


class DailyFeedConfig(Base):
    __tablename__ = "daily_feed_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    attachments: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_creators: Mapped[list] = mapped_column(JSON, default=list)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DailyFeedRun(Entity, Base):
    __tablename__ = "daily_feed_runs"
    day: Mapped[str] = mapped_column(String(10), unique=True)
    summary_status: Mapped[str] = mapped_column(String(20), default="pending")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    diagnostic: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DailyFeedItem(Entity, Base):
    __tablename__ = "daily_feed_items"
    __table_args__ = (UniqueConstraint("run_id", "video_id"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("daily_feed_runs.id"), index=True)
    video_id: Mapped[str] = mapped_column(String(128), index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String(30))
    link_status: Mapped[str] = mapped_column(String(20), default="pending")
    attachment_status: Mapped[str] = mapped_column(String(30), default="not_authorized")
    diagnostic: Mapped[str] = mapped_column(Text, default="")


class LinkImport(Entity, Base):
    __tablename__ = "link_imports"
    source_url: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20))
    authorization: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[str] = mapped_column(Text, default="Waiting for worker")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    media_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"))
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    moments: Mapped[list] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

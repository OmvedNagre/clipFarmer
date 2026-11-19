import re
import shutil
from typing import Literal
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import DiscoverySchedule, WatchMoment, WatchSession, utcnow
from app.schemas import SearchRequest

router = APIRouter()


def canonical_stream(url):
    p = urlparse(url)
    if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Use a public HTTPS YouTube or Twitch link")
    host = (p.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "youtu.be"}:
        video = p.path.strip("/") if host == "youtu.be" else parse_qs(p.query).get("v", [""])[0]
        if p.path.startswith("/live/"):
            video = p.path.split("/")[2]
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            raise ValueError("Use a specific YouTube video or live URL")
        return "youtube", f"https://www.youtube.com/watch?v={video}"
    if host in {"twitch.tv", "www.twitch.tv"} and re.fullmatch(r"/[A-Za-z0-9_]{3,25}/?", p.path):
        return "twitch", "https://www.twitch.tv/" + p.path.strip("/").lower()
    raise ValueError("Use a YouTube live video or Twitch channel link")


class WatchRequest(BaseModel):
    source_url: str = Field(max_length=500)
    creator_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    creator_name: str = Field(min_length=1, max_length=200)
    authorization_notes: str = Field(min_length=5, max_length=4000)
    authorized: Literal[True]
    ratio: float = Field(default=3, ge=1.5, le=10, allow_inf_nan=False)
    minimum: int = Field(default=10, ge=3, le=10000)
    distinct: int = Field(default=5, ge=2, le=1000)
    pre_roll: int = Field(default=30, ge=5, le=120)
    post_roll: int = Field(default=15, ge=5, le=120)
    chat_delay: float = Field(default=0, ge=-60, le=60, allow_inf_nan=False)
    max_hours: int = Field(default=12, ge=1, le=24)
    auto_render: bool = True
    transcribe: bool = False

    @model_validator(mode="after")
    def validate_source(self):
        canonical_stream(self.source_url)
        return self


def serialize(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


@router.get("/watch/status")
def status():
    s = get_settings()
    return {
        "streamlink": bool(shutil.which(s.streamlink_binary)),
        "ffmpeg": bool(shutil.which(s.ffmpeg_binary)),
        "youtube_configured": bool(s.youtube_api_key.get_secret_value()),
        "twitch_configured": bool(
            s.twitch_client_id and s.twitch_user_token.get_secret_value() and s.twitch_chat_login
        ),
        "local_captions_configured": bool(s.whisper_model_path and shutil.which(s.whisper_binary)),
        "max_sessions": s.live_max_sessions,
    }


@router.get("/watch/sessions")
def sessions(db: Session = Depends(get_db)):
    return [
        serialize(r)
        for r in db.scalars(
            select(WatchSession).order_by(WatchSession.created_at.desc()).limit(100)
        )
    ]


@router.post("/watch/sessions", status_code=201)
def create(request: WatchRequest, db: Session = Depends(get_db)):
    platform, url = canonical_stream(request.source_url)
    active = db.scalar(
        select(WatchSession).where(
            WatchSession.source_url == url,
            WatchSession.status.in_(["queued", "waiting", "recording", "reconnecting"]),
        )
    )
    if active:
        raise HTTPException(409, "This stream is already being watched")
    row = WatchSession(
        platform=platform,
        source_url=url,
        creator_id=request.creator_id,
        creator_name=request.creator_name,
        authorization_notes=request.authorization_notes,
        options=request.model_dump(
            exclude={
                "source_url",
                "creator_id",
                "creator_name",
                "authorization_notes",
                "authorized",
            }
        ),
    )
    db.add(row)
    db.commit()
    return serialize(row)


@router.post("/watch/sessions/{session_id}/stop")
def stop(session_id: str, db: Session = Depends(get_db)):
    row = db.get(WatchSession, session_id)
    if not row:
        raise HTTPException(404, "Watch session not found")
    row.stop_requested = True
    if row.status == "queued":
        row.status, row.ended_at = "stopped", utcnow()
    db.commit()
    return serialize(row)


@router.get("/watch/sessions/{session_id}/moments")
def moments(session_id: str, db: Session = Depends(get_db)):
    return [
        serialize(r)
        for r in db.scalars(
            select(WatchMoment)
            .where(WatchMoment.watch_session_id == session_id)
            .order_by(WatchMoment.created_at)
        )
    ]


class ScheduleRequest(SearchRequest):
    creator_ids: list[str] = Field(min_length=1, max_length=100)
    interval_minutes: int = Field(default=60, ge=15, le=10080)

    @model_validator(mode="after")
    def supported(self):
        if set(self.platforms) - {"youtube", "twitch", "reddit", "x"}:
            raise ValueError("Scheduled discovery supports YouTube, Twitch, Reddit and X")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", x) for x in self.creator_ids):
            raise ValueError("Use platform creator IDs, not display names")
        return self


@router.get("/discovery/schedules")
def schedules(db: Session = Depends(get_db)):
    return [
        serialize(r)
        for r in db.scalars(select(DiscoverySchedule).order_by(DiscoverySchedule.created_at.desc()))
    ]


@router.post("/discovery/schedules", status_code=201)
def schedule(request: ScheduleRequest, db: Session = Depends(get_db)):
    row = DiscoverySchedule(
        query=request.query,
        platforms=request.platforms,
        creator_ids=request.creator_ids,
        interval_minutes=request.interval_minutes,
    )
    db.add(row)
    db.commit()
    return serialize(row)


class SchedulePatch(BaseModel):
    enabled: bool


@router.patch("/discovery/schedules/{schedule_id}")
def toggle(schedule_id: str, request: SchedulePatch, db: Session = Depends(get_db)):
    row = db.get(DiscoverySchedule, schedule_id)
    if not row:
        raise HTTPException(404, "Schedule not found")
    row.enabled = request.enabled
    db.commit()
    return serialize(row)

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import DailyFeedItem, DailyFeedRun, LinkImport, MediaAsset, ProcessingJob
from app.schemas.media import JobRequest
from app.services.daily_feed import ensure_config, reserve_run
from app.services.media import AUTHORIZED, storage_path
from app.services.video_links import normalize_url

router = APIRouter()


def record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class ImportRequest(BaseModel):
    source_url: str = Field(max_length=500)
    mode: Literal["video", "stream"] = "video"
    authorization: Literal["user_owned", "creator_authorized", "licensed"] = "creator_authorized"
    permission_confirmed: bool = False
    notes: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_request(self):
        self.source_url = normalize_url(self.source_url)
        if self.mode == "stream":
            self.authorization = "user_owned"
            self.notes = "User requested analysis of their own livestream recording"
        elif not self.permission_confirmed:
            raise ValueError("Confirm you own or have permission to download this video")
        return self


@router.post("/links", status_code=201)
def create_link(payload: ImportRequest, db: Session = Depends(get_db)):
    existing = db.scalar(
        select(LinkImport).where(
            LinkImport.source_url == payload.source_url,
            LinkImport.mode == payload.mode,
            LinkImport.status.in_(["queued", "running"]),
        )
    )
    if existing:
        raise HTTPException(409, "This link is already being processed")
    if (
        db.scalar(
            select(func.count())
            .select_from(LinkImport)
            .where(LinkImport.status.in_(["queued", "running"]))
        )
        >= 10
    ):
        raise HTTPException(429, "Link queue is full; wait for an existing job to finish")
    row = LinkImport(
        source_url=payload.source_url,
        mode=payload.mode,
        authorization=payload.authorization,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    return record(row)


@router.get("/links")
def list_links(db: Session = Depends(get_db)):
    return [
        record(row)
        for row in db.scalars(select(LinkImport).order_by(LinkImport.created_at.desc()).limit(100))
    ]


@router.post("/links/{job_id}/cancel")
def cancel(job_id: str, db: Session = Depends(get_db)):
    row = db.get(LinkImport, job_id)
    if not row:
        raise HTTPException(404, "Link job not found")
    row.cancel_requested = True
    if row.status == "queued":
        row.status = "cancelled"
        row.progress = "Cancelled"
    db.commit()
    return record(row)


@router.get("/links/{job_id}/download")
def download(job_id: str, db: Session = Depends(get_db)):
    row = db.get(LinkImport, job_id)
    if not row or row.status != "ready" or not row.media_asset_id:
        raise HTTPException(409, "Video is not ready")
    asset = db.get(MediaAsset, row.media_asset_id)
    if not asset or asset.authorization_status not in AUTHORIZED or asset.archived:
        raise HTTPException(409, "This source is unavailable")
    path = storage_path(asset.storage_path)
    if not path.is_file():
        raise HTTPException(404, "Source file is missing")
    return FileResponse(path, media_type=asset.mime_type, filename=f"clipforge-{row.id}.mp4")


class ClipRequest(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    profile: Literal["original", "shorts_720x1280", "shorts_1080x1920"] = "shorts_720x1280"


@router.post("/links/{job_id}/clip", status_code=201)
def clip(job_id: str, payload: ClipRequest, db: Session = Depends(get_db)):
    row = db.get(LinkImport, job_id)
    if not row or row.status != "ready" or not row.media_asset_id:
        raise HTTPException(409, "Source is not ready")
    asset = db.get(MediaAsset, row.media_asset_id)
    if not asset or asset.archived or asset.authorization_status not in AUTHORIZED:
        raise HTTPException(409, "Source is unavailable")
    if payload.end <= payload.start or payload.end > asset.duration_seconds:
        raise HTTPException(422, "Choose a valid clip window within the recording")
    if (
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status.in_(["queued", "running"]))
        )
        >= 20
    ):
        raise HTTPException(429, "Render queue is full")
    options = JobRequest(
        media_id=asset.id,
        profiles=[payload.profile],
        trim_start_seconds=payload.start,
        trim_end_seconds=payload.end,
    ).model_dump(exclude={"media_id"})
    options["subtitle_srt"] = asset.subtitle_srt
    job = ProcessingJob(media_asset_id=asset.id, options=options)
    db.add(job)
    db.commit()
    return {"id": job.id, "status": job.status}


@router.get("/daily-feed")
def feed(db: Session = Depends(get_db)):
    config = ensure_config(db)
    runs = list(db.scalars(select(DailyFeedRun).order_by(DailyFeedRun.day.desc()).limit(14)))
    ids = [r.id for r in runs]
    items = (
        list(
            db.scalars(
                select(DailyFeedItem)
                .where(DailyFeedItem.run_id.in_(ids))
                .order_by(DailyFeedItem.created_at)
            )
        )
        if ids
        else []
    )
    return {
        "config": record(config),
        "timezone": "Asia/Kolkata",
        "gameplay_not_before": get_settings().daily_gameplay_not_before.isoformat(),
        "limit": 20,
        "runs": [record(r) for r in runs],
        "items": [record(i) for i in items],
    }


class FeedPatch(BaseModel):
    enabled: bool
    attachments: bool
    approved_creators: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_creators(self):
        if any(not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", value) for value in self.approved_creators):
            raise ValueError("Use YouTube channel IDs beginning with UC")
        return self


@router.patch("/daily-feed")
def patch_feed(payload: FeedPatch, db: Session = Depends(get_db)):
    row = ensure_config(db)
    row.enabled = payload.enabled
    row.attachments = payload.attachments
    row.approved_creators = payload.approved_creators
    db.commit()
    return record(row)


@router.post("/daily-feed/run", status_code=201)
def run_now(db: Session = Depends(get_db)):
    if not ensure_config(db).enabled:
        raise HTTPException(409, "Enable the feed first")
    rid = reserve_run(db)
    if rid is None:
        raise HTTPException(409, "Today's feed already has a run; the next reset is midnight IST")
    return {"id": rid, "status": "queued"}

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    DiscoveredItem,
    JobEvent,
    MediaAsset,
    ProcessingJob,
    ReviewAction,
    VideoOutput,
)
from app.schemas import ItemResponse
from app.schemas.media import (
    Authorization,
    ConfirmDelete,
    JobRequest,
    JobResponse,
    MediaPatch,
    MediaResponse,
    OutputMediaResponse,
    OutputResponse,
    ReviewRequest,
)
from app.services.media import AUTHORIZED, import_upload, parse_srt, storage_path
from app.services.processing import capabilities, event

router = APIRouter()


def get_record(db, model, identity):
    value = db.get(model, identity)
    if value is None:
        raise HTTPException(404, "Record not found")
    return value


def has_active_jobs(db, identity):
    return db.scalar(
        select(ProcessingJob.id)
        .where(
            ProcessingJob.media_asset_id == identity,
            ProcessingJob.status.in_(["queued", "running"]),
        )
        .limit(1)
    )


@router.post("/media/upload", response_model=MediaResponse)
def upload(
    file: UploadFile = File(...),
    authorization_status: Authorization = Form(...),
    authorization_notes: str = Form("", max_length=4000),
    discovered_item_id: str | None = Form(None),
    source_url: str = Form("", max_length=2000),
    db: Session = Depends(get_db),
):
    if discovered_item_id:
        get_record(db, DiscoveredItem, discovered_item_id)
    if source_url:
        parsed = urlparse(source_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
        ):
            raise HTTPException(
                422, "Use a public source URL without credentials or query parameters."
            )
    return import_upload(
        db, file, authorization_status, authorization_notes, discovered_item_id, source_url
    )


@router.get("/media", response_model=list[MediaResponse])
def list_media(
    q: str = "",
    archived: bool = False,
    authorization_status: Authorization | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(MediaAsset).where(MediaAsset.archived == archived)
    if q:
        stmt = stmt.where(MediaAsset.original_filename.icontains(q, autoescape=True))
    if authorization_status:
        stmt = stmt.where(MediaAsset.authorization_status == authorization_status)
    return db.scalars(stmt.order_by(MediaAsset.created_at.desc()).offset(offset).limit(limit)).all()


@router.get("/media/{media_id}", response_model=MediaResponse)
def media_detail(media_id: str, db: Session = Depends(get_db)):
    return get_record(db, MediaAsset, media_id)


@router.patch("/media/{media_id}", response_model=MediaResponse)
def media_patch(media_id: str, payload: MediaPatch, db: Session = Depends(get_db)):
    asset = get_record(db, MediaAsset, media_id)
    if has_active_jobs(db, media_id):
        raise HTTPException(409, "Wait for or cancel active jobs before editing this asset.")
    changes = payload.model_dump(exclude_none=True)
    if "subtitle_srt" in changes:
        parse_srt(changes["subtitle_srt"])
    if changes:
        asset.review_status = "pending"
    for key, value in changes.items():
        setattr(asset, key, value)
    db.commit()
    return asset


@router.delete("/media/{media_id}")
def delete_media(media_id: str, payload: ConfirmDelete, db: Session = Depends(get_db)):
    asset = get_record(db, MediaAsset, media_id)
    if not payload.confirm:
        raise HTTPException(400, "Explicit confirmation is required.")
    if db.scalar(select(ProcessingJob.id).where(ProcessingJob.media_asset_id == media_id).limit(1)):
        raise HTTPException(
            409, "This asset has processing history. Archive it to preserve the audit trail."
        )
    path = storage_path(asset.storage_path)
    for review in db.scalars(select(ReviewAction).where(ReviewAction.media_asset_id == media_id)):
        db.delete(review)
    db.delete(asset)
    db.commit()
    if payload.delete_file:
        path.unlink(missing_ok=True)
    return {"deleted": True, "file_deleted": payload.delete_file}


def download(path, filename, mime, preview=False):
    path = storage_path(path)
    if not path.is_file():
        raise HTTPException(404, "File is missing from local storage.")
    return FileResponse(
        path,
        filename=filename,
        media_type=mime,
        content_disposition_type="inline" if preview else "attachment",
    )


@router.get("/media/{media_id}/download")
def media_download(media_id: str, preview: bool = False, db: Session = Depends(get_db)):
    asset = get_record(db, MediaAsset, media_id)
    return download(asset.storage_path, asset.original_filename, asset.mime_type, preview)


@router.post("/processing/jobs", response_model=JobResponse)
def create_job(payload: JobRequest, db: Session = Depends(get_db)):
    asset = get_record(db, MediaAsset, payload.media_id)
    if asset.archived or asset.authorization_status not in AUTHORIZED:
        raise HTTPException(
            403,
            "Confirm ownership, creator permission, or a license before processing an active asset.",
        )
    if payload.trim_start_seconds >= asset.duration_seconds or (
        payload.trim_end_seconds is not None
        and payload.trim_end_seconds > asset.duration_seconds + 0.01
    ):
        raise HTTPException(422, "Trim timestamps must fall within the source video duration.")
    caps = capabilities()
    if not caps["ffmpeg"]:
        raise HTTPException(503, "Install FFmpeg and FFprobe before processing.")
    if payload.burn_subtitles and (not caps["subtitles"] or not asset.subtitle_srt.strip()):
        raise HTTPException(
            422,
            "Burn-in requires saved SRT captions and an FFmpeg build with the subtitles filter (libass). Sidecar SRT remains available.",
        )
    options = payload.model_dump(exclude={"media_id"})
    options["subtitle_srt"] = asset.subtitle_srt
    if (
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status.in_(["queued", "running"]))
        )
        >= 20
    ):
        raise HTTPException(429, "The local queue is full. Wait for jobs to finish.")
    job = ProcessingJob(media_asset_id=asset.id, options=options)
    db.add(job)
    db.flush()
    asset.review_status = "pending"
    event(db, job, "queued", "Job queued; source media retained.")
    db.commit()
    return job


@router.get("/processing/jobs", response_model=list[JobResponse])
def jobs(
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(ProcessingJob).order_by(ProcessingJob.created_at.desc()).offset(offset).limit(limit)
    ).all()


@router.get("/processing/jobs/{job_id}", response_model=JobResponse)
def job_detail(job_id: str, db: Session = Depends(get_db)):
    return get_record(db, ProcessingJob, job_id)


@router.get("/processing/jobs/{job_id}/events")
def events(job_id: str, db: Session = Depends(get_db)):
    get_record(db, ProcessingJob, job_id)
    return [
        {
            "id": e.id,
            "attempt": e.attempt,
            "status": e.status,
            "message": e.message,
            "created_at": e.created_at,
        }
        for e in db.scalars(
            select(JobEvent)
            .where(JobEvent.processing_job_id == job_id)
            .order_by(JobEvent.created_at)
        )
    ]


@router.post("/processing/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = get_record(db, ProcessingJob, job_id)
    if job.status not in {"queued", "running"}:
        raise HTTPException(409, "Only queued or running jobs can be cancelled.")
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
    event(db, job, "cancel_requested", "Cancellation requested by user.")
    db.commit()
    return job


@router.post("/processing/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str, db: Session = Depends(get_db)):
    job = get_record(db, ProcessingJob, job_id)
    asset = get_record(db, MediaAsset, job.media_asset_id)
    if asset.authorization_status not in AUTHORIZED or asset.archived:
        raise HTTPException(403, "Asset must be active and authorized.")
    if job.status != "failed" or not job.retryable or job.attempt_count >= job.max_attempts:
        raise HTTPException(
            409, "This job cannot be retried. Correct the source/options and create a new job."
        )
    job.status = "queued"
    job.cancel_requested = False
    job.progress_percent = 0
    event(db, job, "retry", "Retry requested; previous attempt retained in history.")
    db.commit()
    return job


@router.get("/processing/jobs/{job_id}/outputs", response_model=list[OutputResponse])
def job_outputs(job_id: str, db: Session = Depends(get_db)):
    get_record(db, ProcessingJob, job_id)
    return db.scalars(select(VideoOutput).where(VideoOutput.processing_job_id == job_id)).all()


@router.get("/outputs", response_model=list[OutputResponse])
def outputs(
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    records = db.execute(
        select(VideoOutput, MediaAsset)
        .join(ProcessingJob, VideoOutput.processing_job_id == ProcessingJob.id)
        .join(MediaAsset, ProcessingJob.media_asset_id == MediaAsset.id)
        .order_by(VideoOutput.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        OutputResponse.model_validate(output).model_copy(
            update={"media": OutputMediaResponse.model_validate(asset)}
        )
        for output, asset in records
    ]


@router.get("/outputs/{output_id}/download")
def output_download(output_id: str, preview: bool = False, db: Session = Depends(get_db)):
    output = get_record(db, VideoOutput, output_id)
    job = get_record(db, ProcessingJob, output.processing_job_id)
    asset = get_record(db, MediaAsset, job.media_asset_id)
    if not preview and asset.review_status != "approved":
        raise HTTPException(409, "Approve this asset in Outputs before downloading.")
    return download(output.storage_path, output.filename, output.mime_type, preview)


@router.get("/outputs/{output_id}/subtitles")
def subtitles(output_id: str, db: Session = Depends(get_db)):
    output = get_record(db, VideoOutput, output_id)
    if not output.subtitle_srt:
        raise HTTPException(404, "No captions saved for this output.")
    return PlainTextResponse(
        output.subtitle_srt,
        headers={"Content-Disposition": f'attachment; filename="{Path(output.filename).stem}.srt"'},
    )


@router.post("/media/{media_id}/review", response_model=MediaResponse)
def review(media_id: str, payload: ReviewRequest, db: Session = Depends(get_db)):
    asset = get_record(db, MediaAsset, media_id)
    if has_active_jobs(db, media_id):
        raise HTTPException(409, "Wait for all processing jobs to finish before review.")
    if payload.action == "approved" and asset.authorization_status not in AUTHORIZED:
        raise HTTPException(403, "Approval requires authorized media.")
    asset.review_status = payload.action
    db.add(ReviewAction(media_asset_id=media_id, action=payload.action, notes=payload.notes))
    db.commit()
    return asset


@router.get("/media/{media_id}/reviews")
def reviews(media_id: str, db: Session = Depends(get_db)):
    get_record(db, MediaAsset, media_id)
    return [
        {"action": r.action, "notes": r.notes, "created_at": r.created_at}
        for r in db.scalars(
            select(ReviewAction)
            .where(ReviewAction.media_asset_id == media_id)
            .order_by(ReviewAction.created_at)
        )
    ]


@router.post("/clips/{clip_id}/approve", response_model=MediaResponse)
def approve(clip_id: str, db: Session = Depends(get_db)):
    return review(clip_id, ReviewRequest(action="approved"), db)


@router.post("/clips/{clip_id}/reject", response_model=MediaResponse)
def reject(clip_id: str, db: Session = Depends(get_db)):
    return review(clip_id, ReviewRequest(action="rejected"), db)


@router.delete("/clips/{clip_id}")
def unsave(clip_id: str, payload: ConfirmDelete, db: Session = Depends(get_db)):
    if not payload.confirm:
        raise HTTPException(400, "Confirm removal from the library.")
    item = get_record(db, DiscoveredItem, clip_id)
    item.saved = False
    db.commit()
    return {"removed": True, "source_files_deleted": False}


@router.get("/stats/processing")
def processing_stats(db: Session = Depends(get_db)):
    counts = dict(
        db.execute(select(ProcessingJob.status, func.count()).group_by(ProcessingJob.status)).all()
    )
    return {
        state: counts.get(state, 0)
        for state in ["queued", "running", "completed", "failed", "cancelled"]
    }


class SubmitSource(BaseModel):
    url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    creator_name: str = Field(default="User-submitted source", max_length=200)


@router.post("/discovery/submit", response_model=ItemResponse)
def submit_source(payload: SubmitSource, db: Session = Depends(get_db)):
    host = payload.url.host.lower().removeprefix("www.")
    platforms = {
        "youtube.com": "youtube",
        "youtu.be": "youtube",
        "reddit.com": "reddit",
        "twitch.tv": "twitch",
        "clips.twitch.tv": "twitch",
        "tiktok.com": "tiktok",
        "x.com": "x",
        "twitter.com": "x",
        "instagram.com": "instagram",
    }
    platform = platforms.get(host)
    if not platform or payload.url.username or payload.url.password:
        raise HTTPException(
            422, "Submit a public URL from YouTube, Reddit, Twitch, TikTok, X or Instagram."
        )
    # Preserve only the video identifier query on YouTube; discard tracking and private query values.
    from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

    parts = urlsplit(str(payload.url))
    query = parse_qs(parts.query)
    public_query = (
        urlencode({"v": query["v"][0]}) if platform == "youtube" and query.get("v") else ""
    )
    canonical = urlunsplit(("https", parts.netloc, parts.path, public_query, ""))
    external = "submitted-" + sha256(canonical.encode()).hexdigest()
    item = db.scalar(
        select(DiscoveredItem).where(
            DiscoveredItem.platform == platform, DiscoveredItem.external_id == external
        )
    )
    if not item:
        item = DiscoveredItem(
            platform=platform,
            external_id=external,
            title=payload.title,
            creator_name=payload.creator_name,
            canonical_url=canonical,
            published_at=datetime.now(UTC),
            saved=True,
            raw_metadata={
                "demo": False,
                "user_submitted": True,
                "timestamp_type": "submission_time",
            },
        )
        db.add(item)
    else:
        item.saved = True
    db.commit()
    return item

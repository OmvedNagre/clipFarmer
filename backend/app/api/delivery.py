import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.media import get_record
from app.core.config import get_settings
from app.db.session import get_db
from app.models import DeliveryRecord, MediaAsset, ProcessingJob, VideoOutput, utcnow
from app.services.assistance import get_provider
from app.services.media import AUTHORIZED, storage_path

router = APIRouter()


def telegram_config():
    settings = get_settings()
    if not settings.telegram_bot_token.get_secret_value() or not settings.telegram_chat_id:
        raise HTTPException(
            409, "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env, then restart."
        )
    return settings


@router.post("/telegram/test")
async def test_telegram():
    settings = telegram_config()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token.get_secret_value()}/getMe"
            )
            data = response.json()
            if not response.is_success or not data.get("ok"):
                raise ValueError()
            chat = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token.get_secret_value()}/getChat",
                params={"chat_id": settings.telegram_chat_id},
            )
            if not chat.is_success or not chat.json().get("ok"):
                raise ValueError()
        return {
            "status": "connected",
            "message": "Bot credentials and destination are reachable. Sending rights are verified when delivering a file.",
        }
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            502,
            "Telegram connection failed. Check the bot token, destination, and bot access to that chat.",
        ) from None


class DeliveryRequest(BaseModel):
    confirm_resend: bool = False


@router.post("/outputs/{output_id}/telegram-send")
async def send_telegram(output_id: str, payload: DeliveryRequest, db: Session = Depends(get_db)):
    settings = telegram_config()
    output = get_record(db, VideoOutput, output_id)
    job = get_record(db, ProcessingJob, output.processing_job_id)
    asset = get_record(db, MediaAsset, job.media_asset_id)
    if asset.review_status != "approved" or asset.authorization_status not in AUTHORIZED:
        raise HTTPException(409, "Approve authorized media before sending it to Telegram.")
    if output.size_bytes > settings.telegram_max_upload_mb * 1024 * 1024:
        raise HTTPException(
            413,
            "Output exceeds the configured Telegram limit. Download it locally or render a shorter/lower-resolution clip.",
        )
    previous = db.scalars(
        select(DeliveryRecord).where(DeliveryRecord.video_output_id == output_id)
    ).all()
    if any(r.status == "sending" for r in previous):
        raise HTTPException(409, "Delivery is already in progress.")
    if not payload.confirm_resend and any(r.status in {"sent", "unknown"} for r in previous):
        raise HTTPException(
            409,
            "This file was sent or its delivery is uncertain. Check Telegram, then explicitly confirm resend.",
        )
    path = storage_path(output.storage_path)
    if not path.is_file():
        raise HTTPException(404, "Output file is missing.")
    record = DeliveryRecord(video_output_id=output_id, status="sending")
    db.add(record)
    db.commit()
    metadata = asset.publishing_metadata
    caption = (
        "\n\n".join(str(metadata.get(k, "")) for k in ["title", "description", "hashtags"]).strip()
        or output.filename
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            with path.open("rb") as video:
                response = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token.get_secret_value()}/sendVideo",
                    data={
                        "chat_id": settings.telegram_chat_id,
                        "caption": caption[:1024],
                        "supports_streaming": "true",
                    },
                    files={"video": (output.filename, video, "video/mp4")},
                )
            data = response.json()
            if not response.is_success or not data.get("ok"):
                record.status = "failed"
                record.error_message = (
                    "Telegram rejected the delivery. Check chat permissions and file limits."
                )
            else:
                record.status = "sent"
                record.external_message_id = str(data["result"]["message_id"])
                record.sent_at = utcnow()
    except (httpx.HTTPError, ValueError, KeyError):
        record.status = "unknown"
        record.error_message = (
            "Delivery outcome is uncertain. Check Telegram before retrying to avoid duplicates."
        )
    db.commit()
    return {
        "id": record.id,
        "status": record.status,
        "error_message": record.error_message,
        "sent_at": record.sent_at,
    }


@router.get("/outputs/{output_id}/deliveries")
def delivery_history(output_id: str, db: Session = Depends(get_db)):
    get_record(db, VideoOutput, output_id)
    return [
        {"id": r.id, "status": r.status, "error_message": r.error_message, "sent_at": r.sent_at}
        for r in db.scalars(
            select(DeliveryRecord)
            .where(DeliveryRecord.video_output_id == output_id)
            .order_by(DeliveryRecord.created_at.desc())
        )
    ]


class SuggestRequest(BaseModel):
    context: str = Field(min_length=1, max_length=5000)


@router.post("/ai/suggest")
async def suggest(payload: SuggestRequest):
    return await get_provider().suggest(payload.context)


@router.post("/media/{media_id}/transcribe")
async def transcribe(media_id: str, db: Session = Depends(get_db)):
    asset = get_record(db, MediaAsset, media_id)
    if asset.authorization_status not in AUTHORIZED:
        raise HTTPException(403, "Authorize the source before sending its audio for transcription.")
    return {"subtitle_srt": await get_provider().transcribe(asset)}

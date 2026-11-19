import asyncio
import re
import shutil
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.adapters.live import YouTubeAdapter
from app.core.config import get_settings
from app.models import DailyFeedConfig, DailyFeedItem, DailyFeedRun, utcnow
from app.services.media import run_probe, storage_path
from app.services.video_links import LinkCancelled, fetch_video, inspect_video, sampled_faces

ZONE = ZoneInfo("Asia/Kolkata")


def next_midnight(now=None):
    local = (now or utcnow()).astimezone(ZONE)
    return datetime.combine(local.date() + timedelta(days=1), time(), ZONE).astimezone(UTC)


def ensure_config(db):
    config = db.get(DailyFeedConfig, 1)
    if config is None:
        config = DailyFeedConfig(id=1, next_run_at=next_midnight())
        db.add(config)
        db.commit()
    return config


def gameplay_match(title):
    title = title.casefold()
    game = bool(re.search(r"\b(?:gta\s*(?:6|vi)|grand theft auto\s*(?:6|vi))\b", title))
    footage = bool(
        re.search(r"\b(?:gameplay|playthrough|walkthrough|mission|playing|let['’]?s play)\b", title)
    )
    excluded = bool(
        re.search(
            r"\b(?:trailer|teaser|reaction|reacts|news|rumou?r|leak(?:ed|s)?|speculation|concept|fanmade|fan-made|mod(?:s|ded)?|prediction|wishlist|breakdown|analysis|explained|fake|ai.generated|release date|south park|superheroes|superhero|roblox|minecraft|fortnite|reacciona|reaccion|reacción|información|gta\s*(?:5|v)|coming soon)\b",
            title,
        )
    )
    return game and footage and not excluded


async def discover_candidates():
    publication_floor = datetime.combine(
        get_settings().daily_gameplay_not_before, time(), ZONE
    ).astimezone(UTC)
    if utcnow() < publication_floor:
        return []
    adapter = YouTubeAdapter()
    results = []
    for query in ("GTA VI gameplay", "GTA 6 gameplay", "Grand Theft Auto VI walkthrough"):
        results.extend(
            await adapter.search(
                query,
                50,
                sort="engagement",
                published_after=max(utcnow() - timedelta(days=30), publication_floor),
            )
        )
    unique = {
        row.external_id: row
        for row in results
        if gameplay_match(row.title)
        and row.raw_metadata.get("live") == "none"
        and row.raw_metadata.get("category_id") == "20"
        and (row.duration_seconds or 0) > 0
    }
    return sorted(
        unique.values(), key=lambda row: (row.view_count or 0, row.published_at), reverse=True
    )


def reserve_run(db, now=None):
    now = now or utcnow()
    config = ensure_config(db)
    day = now.astimezone(ZONE).date().isoformat()
    existing = db.scalar(select(DailyFeedRun).where(DailyFeedRun.day == day))
    config.next_run_at = next_midnight(now)
    if existing:
        db.commit()
        return None
    row = DailyFeedRun(day=day)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return row.id


def telegram(method, payload, file=None):
    s = get_settings()
    if not s.telegram_bot_token.get_secret_value() or not s.telegram_chat_id:
        return "failed", "Telegram is not configured"
    try:
        with httpx.Client(timeout=180 if file else 20, follow_redirects=False) as client:
            url = (
                "https://api.telegram.org/bot"
                + s.telegram_bot_token.get_secret_value()
                + "/"
                + method
            )
            if file:
                with file.open("rb") as handle:
                    response = client.post(
                        url,
                        data={"chat_id": s.telegram_chat_id, **payload},
                        files={"video": (file.name, handle, "video/mp4")},
                    )
            else:
                response = client.post(url, json={"chat_id": s.telegram_chat_id, **payload})
            if response.status_code >= 500:
                return (
                    "unknown",
                    "Telegram server error; delivery outcome is uncertain and will not be retried automatically",
                )
            data = response.json()
            if response.is_success and data.get("ok"):
                return "sent", "Delivered"
            return "failed", "Telegram rejected delivery; check bot access, limits and destination"
    except (httpx.HTTPError, ValueError):
        return "unknown", "Delivery outcome uncertain; check Telegram before any manual resend"


def deliver_item(factory, item_id, stopped=lambda: False):
    with factory() as db:
        item = db.get(DailyFeedItem, item_id)
        config = ensure_config(db)
        snapshot = dict(item.snapshot)
        if stopped() or not config.enabled:
            return
        if item.link_status == "pending":
            item.link_status = "sending"
            db.commit()
            text = (
                f"GTA VI gameplay candidate · {item.category}\n{snapshot['title'][:250]}\n"
                f"Creator: {snapshot['creator_name']}\nViews at discovery: {snapshot.get('view_count') or 0:,}\n"
                f"{snapshot['canonical_url']}\n{snapshot['classification']}\n"
                "Title-based gameplay match; authenticity is not independently verified. Paste this link in ClipForge to download or edit an authorized source."
            )
            status, note = telegram(
                "sendMessage", {"text": text, "link_preview_options": {"is_disabled": False}}
            )
            item.link_status = status
            item.diagnostic = note
            db.commit()
        if stopped() or item.link_status != "sent" or item.attachment_status != "pending":
            return
        if not config.attachments:
            item.attachment_status = "disabled"
            db.commit()
            return
        allowed = (
            snapshot.get("license") == "creativeCommon"
            or snapshot.get("creator_id") in config.approved_creators
        )
        if not allowed:
            item.attachment_status = "not_authorized"
            db.commit()
            return
        work = storage_path(f"daily-downloads/{item.id}")
        try:
            info = inspect_video(snapshot["canonical_url"], work, stopped)
            # Prevent a changed source identity from inheriting an allowlist permission.
            if info.get("channel_id") != snapshot.get("creator_id"):
                raise ValueError("Source owner changed")
            file = fetch_video(snapshot["canonical_url"], work, stopped)[0]
            probe = run_probe(file)
            if file.stat().st_size > get_settings().telegram_max_upload_mb * 1024**2:
                item.attachment_status = "too_large"
                item.diagnostic = "Link delivered; video exceeds Telegram file budget"
            elif probe["video_codec"] != "h264":
                item.attachment_status = "unsupported_codec"
                item.diagnostic = "Link delivered; source needs H.264 rendering in the editor"
            else:
                item.attachment_status = "sending"
                db.commit()
                license_note = (
                    " · YouTube-declared Creative Commons license"
                    if snapshot.get("license") == "creativeCommon"
                    else " · Creator authorized"
                )
                status, note = telegram(
                    "sendVideo",
                    {
                        "caption": f"{snapshot['title'][:200]}\nCredit: {snapshot['creator_name']}\n{snapshot['canonical_url']}{license_note}",
                        "supports_streaming": "true",
                    },
                    file,
                )
                item.attachment_status = status
                item.diagnostic = note
        except LinkCancelled:
            item.attachment_status = "cancelled"
        except Exception:
            item.attachment_status = "unavailable"
            item.diagnostic = (
                "Link delivered; automatic attachment unavailable. Use the source link."
            )
        finally:
            db.commit()
            shutil.rmtree(work, ignore_errors=True)


def run_feed(factory, run_id, stopped=lambda: False):
    with factory() as db:
        run = db.get(DailyFeedRun, run_id)
        run.status = "running"
        db.commit()
        already = set(
            db.scalars(
                select(DailyFeedItem.video_id).where(
                    DailyFeedItem.link_status.in_(["sent", "sending", "unknown"])
                )
            )
        )
    accepted = {"face": 0, "faceless": 0}
    checked = 0
    failed = 0
    try:
        candidates = asyncio.run(discover_candidates())
        for candidate in candidates:
            if stopped():
                raise LinkCancelled("Stopped")
            if candidate.external_id in already:
                continue
            if checked >= get_settings().daily_candidate_limit or sum(accepted.values()) >= 20:
                break
            checked += 1
            work = storage_path(f"daily-samples/{run_id}/{candidate.external_id}")
            try:
                info = inspect_video(str(candidate.canonical_url), work, stopped)
                if not gameplay_match(info.get("title", "")):
                    continue
                files = fetch_video(
                    str(candidate.canonical_url), work, stopped, sample=True, info=info
                )
                category, evidence = sampled_faces(files)
                if category not in accepted or accepted[category] >= 10:
                    continue
                snapshot = candidate.model_dump(mode="json")
                snapshot.update(
                    classification=evidence, license=candidate.raw_metadata.get("license")
                )
                with factory() as db:
                    config = ensure_config(db)
                    if not config.enabled:
                        raise LinkCancelled("Paused")
                    authorized = (
                        snapshot.get("license") == "creativeCommon"
                        or candidate.creator_id in config.approved_creators
                    )
                    item = DailyFeedItem(
                        run_id=run_id,
                        video_id=candidate.external_id,
                        snapshot=snapshot,
                        category=category,
                        attachment_status="pending"
                        if config.attachments and authorized
                        else "not_authorized"
                        if config.attachments
                        else "disabled",
                    )
                    db.add(item)
                    db.commit()
                    item_id = item.id
                accepted[category] += 1
                already.add(candidate.external_id)
                deliver_item(factory, item_id, stopped)
            except LinkCancelled:
                raise
            except Exception:
                failed += 1
            finally:
                shutil.rmtree(work, ignore_errors=True)
        with factory() as db:
            run = db.get(DailyFeedRun, run_id)
            run.status = "completed"
            run.diagnostic = f"Selected {accepted['face']}/10 face and {accepted['faceless']}/10 faceless candidates. Inspected {checked}; unavailable checks {failed}. Strict gameplay-title filter; no added filler. Publication window starts {get_settings().daily_gameplay_not_before}. See individual delivery outcomes."
            run.completed_at = utcnow()
            run.summary_status = "sending"
            summary = f"ClipForge daily gameplay feed · {run.day} IST\n{run.diagnostic}"
            db.commit()
            status, _ = telegram("sendMessage", {"text": summary})
            run.summary_status = status
            db.commit()
    except Exception as exc:
        with factory() as db:
            run = db.get(DailyFeedRun, run_id)
            run.status = "interrupted" if isinstance(exc, LinkCancelled) else "failed"
            run.diagnostic = (
                "Feed interrupted; reserved items will not be duplicated."
                if isinstance(exc, LinkCancelled)
                else "Discovery unavailable; check YouTube credentials, quota and connection."
            )
            run.completed_at = utcnow()
            db.commit()

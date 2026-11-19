import fcntl
import logging
import shutil
import threading
from types import SimpleNamespace

from sqlalchemy import select

from app.models import DailyFeedItem, DailyFeedRun, LinkImport, utcnow
from app.services.daily_feed import ensure_config, reserve_run, run_feed
from app.services.media import import_upload, run_probe, storage_path
from app.services.recording_peaks import audio_peaks, heatmap_peaks, replay_peaks
from app.services.video_links import (
    LinkCancelled,
    LinkError,
    fetch_chat,
    fetch_video,
    inspect_video,
)

log = logging.getLogger("clipforge.content")


class ContentWorker:
    def __init__(self, factory):
        self.sessions = factory
        self.stop_event = threading.Event()
        self.threads = []
        self.lock = None

    def start(self):
        path = storage_path(".content-worker.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = path.open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            return
        with self.sessions() as db:
            ensure_config(db)
            for job in db.scalars(select(LinkImport).where(LinkImport.status == "running")):
                job.status = "failed"
                job.progress = "Interrupted by restart. Submit again to retry."
            for run in db.scalars(select(DailyFeedRun).where(DailyFeedRun.status == "running")):
                run.status = "interrupted"
                run.diagnostic = (
                    "Worker restarted; no uncertain deliveries will be retried automatically."
                )
            for run in db.scalars(
                select(DailyFeedRun).where(DailyFeedRun.summary_status == "sending")
            ):
                run.summary_status = "unknown"
            for item in db.scalars(select(DailyFeedItem)):
                if item.link_status == "sending":
                    item.link_status = "unknown"
                if item.attachment_status == "sending":
                    item.attachment_status = "unknown"
            db.commit()
        for folder in ("link-temp", "daily-samples", "daily-downloads"):
            shutil.rmtree(storage_path(folder), ignore_errors=True)
        for target in (self.links_loop, self.feed_loop, self.heartbeat_loop):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=55)
        if self.lock and not any(t.is_alive() for t in self.threads):
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None

    def cancelled(self, jid):
        with self.sessions() as db:
            row = db.get(LinkImport, jid)
            return self.stop_event.is_set() or row is None or row.cancel_requested

    def progress(self, jid, message):
        with self.sessions() as db:
            db.get(LinkImport, jid).progress = message
            db.commit()

    def run_link(self, jid):
        work = storage_path(f"link-temp/{jid}")
        try:
            with self.sessions() as db:
                row = db.get(LinkImport, jid)
                if row.status != "queued":
                    return
                row.status = "running"
                db.commit()
                url, mode, authorization, notes = (
                    row.source_url,
                    row.mode,
                    row.authorization,
                    row.notes,
                )

            def stopped():
                return self.cancelled(jid)

            if stopped():
                raise LinkCancelled("Cancelled")
            self.progress(jid, "Inspecting source")
            info = inspect_video(url, work, stopped)
            self.progress(jid, "Downloading accessible recording")
            file = fetch_video(url, work, stopped)[0]
            probe = run_probe(file)
            self.progress(jid, "Importing video")
            with self.sessions() as db:
                asset = import_upload(
                    db,
                    SimpleNamespace(
                        filename="linked-recording.mp4",
                        content_type="video/mp4",
                        file=file.open("rb"),
                    ),
                    authorization,
                    notes,
                    None,
                    url,
                )
                # Preserve duplicate provenance; the own-stream flow explicitly approves owned media below.
                if (
                    asset.source_provenance.get("type") == "user_upload"
                    and asset.source_provenance.get("source_url") == url
                ):
                    asset.source_provenance = {
                        "type": "own_stream" if mode == "stream" else "authorized_link",
                        "source_url": url,
                        "creator_name": info.get("uploader", "Unknown"),
                    }
                    asset.publishing_metadata = {
                        "title": info.get("title", "Recording")[:200],
                        "description": f"Source: {url}\nCredit: {info.get('uploader', 'Unknown')}",
                        "hook": "",
                        "hashtags": "",
                    }
                if mode == "stream":
                    asset.authorization_status = "user_owned"
                    asset.review_status = "approved"
                row = db.get(LinkImport, jid)
                row.media_asset_id = asset.id
                row.metadata_snapshot = {
                    "title": info.get("title", "Recording"),
                    "creator": info.get("uploader", "Unknown"),
                    "duration": probe["duration_seconds"],
                }
                db.commit()
            moments = []
            method = "No analysis requested"
            if mode == "stream":
                self.progress(jid, "Reading replay engagement")
                chat = fetch_chat(url, work, stopped)
                if chat:
                    moments = replay_peaks(chat, probe["duration_seconds"])
                if moments:
                    method = "Ranked by chat activity; not concurrent viewer counts"
                if not moments:
                    moments = heatmap_peaks(info, probe["duration_seconds"])
                    if moments:
                        method = "Ranked by available platform replay intensity"
                if not moments:
                    self.progress(jid, "No usable engagement data; examining audio")
                    try:
                        moments = audio_peaks(file, work, probe["duration_seconds"], stopped)
                    except LinkCancelled:
                        raise
                    except Exception:
                        moments = []
                    method = (
                        "Audio-only suggestions; no measured audience engagement"
                        if moments
                        else "No reliable peaks found; video is ready for manual trimming"
                    )
            if stopped():
                raise LinkCancelled("Cancelled")
            with self.sessions() as db:
                row = db.get(LinkImport, jid)
                row.moments = moments
                row.status = "ready"
                row.progress = method
                row.completed_at = utcnow()
                db.commit()
        except Exception as exc:
            with self.sessions() as db:
                row = db.get(LinkImport, jid)
                row.status = "cancelled" if isinstance(exc, LinkCancelled) else "failed"
                row.progress = (
                    str(exc)
                    if isinstance(exc, LinkError)
                    else "Import or analysis failed. Try a shorter supported source or upload the file."
                )
                row.completed_at = utcnow()
                db.commit()
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def links_loop(self):
        while not self.stop_event.is_set():
            try:
                with self.sessions() as db:
                    row = db.scalar(
                        select(LinkImport)
                        .where(LinkImport.status == "queued")
                        .order_by(LinkImport.created_at)
                    )
                    jid = row.id if row else None
                if jid:
                    self.run_link(jid)
            except Exception:
                log.warning("Content worker operation failed; retrying on next tick")
            self.stop_event.wait(1)

    def feed_loop(self):
        while not self.stop_event.is_set():
            try:
                with self.sessions() as db:
                    config = ensure_config(db)
                    config.heartbeat_at = utcnow()
                    db.commit()
                    if config.enabled and config.next_run_at <= utcnow():
                        reserve_run(db)
                    run = (
                        db.scalar(
                            select(DailyFeedRun)
                            .where(DailyFeedRun.status == "queued")
                            .order_by(DailyFeedRun.created_at)
                        )
                        if config.enabled
                        else None
                    )
                    rid = run.id if run else None
                if rid:
                    run_feed(self.sessions, rid, self.stop_event.is_set)
            except Exception:
                log.warning("Content worker operation failed; retrying on next tick")
            self.stop_event.wait(15)

    def heartbeat_loop(self):
        while not self.stop_event.is_set():
            try:
                with self.sessions() as db:
                    config = ensure_config(db)
                    config.heartbeat_at = utcnow()
                    db.commit()
            except Exception:
                log.warning("Content worker heartbeat could not be saved")
            self.stop_event.wait(15)

"""Single-consumer durable SQLite queue; worker ownership protected by an OS file lock."""

import fcntl
import json
import logging
import shutil
import subprocess
import threading
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.models import JobEvent, MediaAsset, ProcessingJob, VideoOutput, utcnow
from app.services.media import file_hash, run_probe, storage_path, trimmed_srt

log = logging.getLogger("clipforge.worker")


def event(db, job, status, message):
    db.add(
        JobEvent(
            processing_job_id=job.id, attempt=job.attempt_count, status=status, message=message
        )
    )
    log.info(
        json.dumps(
            {"event": status, "job_id": job.id, "attempt": job.attempt_count, "message": message}
        )
    )


def capabilities():
    settings = get_settings()
    ready = bool(shutil.which(settings.ffmpeg_binary) and shutil.which(settings.ffprobe_binary))
    subtitles = False
    if ready:
        try:
            result = subprocess.run(
                [settings.ffmpeg_binary, "-hide_banner", "-filters"],
                capture_output=True,
                timeout=10,
            )
            subtitles = " subtitles " in result.stdout.decode(errors="replace")
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "ffmpeg": ready,
        "subtitles": subtitles,
        "profiles": ["original", "shorts_1080x1920", "shorts_720x1280"],
    }


def filters(profile, width, height, fps):
    if profile == "original":
        # Even H.264 dimensions; preserve original size and aspect ratio to within one pixel.
        chain = "scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1"
    else:
        w, h = (1080, 1920) if profile == "shorts_1080x1920" else (720, 1280)
        if width / height > 0.8:
            chain = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
        else:
            chain = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if profile != "original":
        chain = "scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1," + chain
    return f"{chain},fps={fps}"


class Cancelled(Exception):
    pass


class Worker:
    def __init__(self, session_factory):
        self.sessions = session_factory
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = None
        self.active = False

    def start(self):
        lock_path = storage_path(".worker.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = lock_path.open("a")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            return
        self.recover()
        self.active = True
        self.thread = threading.Thread(target=self.loop, name="clipforge-worker", daemon=True)
        self.thread.start()

    def recover(self):
        with self.sessions() as db:
            for job in db.scalars(select(ProcessingJob).where(ProcessingJob.status == "running")):
                if job.cancel_requested:
                    job.status = "cancelled"
                elif job.attempt_count < job.max_attempts:
                    job.status = "queued"
                else:
                    job.status = "failed"
                    job.error_code = "restart_limit"
                    job.error_message = (
                        "Interrupted too often. Create a new job from the retained media."
                    )
                event(db, job, "recovered", f"Worker restarted; job {job.status}.")
            # Delivery outcomes cannot safely be retried automatically after interruption.
            from app.models import DeliveryRecord

            for record in db.scalars(
                select(DeliveryRecord).where(DeliveryRecord.status == "sending")
            ):
                record.status = "unknown"
                record.error_message = (
                    "Application restarted during delivery. Check Telegram before resending."
                )
            db.commit()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=40)
        self.active = False
        if self.lock:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            self.lock.close()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                with self.sessions() as db:
                    job = db.scalar(
                        select(ProcessingJob)
                        .where(ProcessingJob.status == "queued")
                        .order_by(ProcessingJob.created_at)
                        .limit(1)
                    )
                    job_id = job.id if job else None
                if job_id:
                    self.run_job(job_id)
                else:
                    self.stop_event.wait(0.4)
            except Exception:
                log.error(
                    json.dumps(
                        {"event": "worker_error", "message": "Worker loop failed; retrying safely."}
                    )
                )
                self.stop_event.wait(2)

    def cancelled(self, job_id):
        with self.sessions() as db:
            job = db.get(ProcessingJob, job_id)
            return self.stop_event.is_set() or job is None or job.cancel_requested

    def run_command(self, args, job_id, work, duration, base, span):
        progress = work / "progress.txt"
        stderr = work / "stderr.txt"
        with progress.open("w") as out, stderr.open("w") as err:
            process = subprocess.Popen(args, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
            deadline = time.monotonic() + get_settings().processing_timeout_seconds
            last = -1
            try:
                while process.poll() is None:
                    if self.cancelled(job_id):
                        raise Cancelled()
                    if time.monotonic() > deadline:
                        raise TimeoutError()
                    try:
                        values = [
                            line.split("=", 1)[1]
                            for line in progress.read_text().splitlines()
                            if line.startswith("out_time_us=")
                        ]
                        percent = (
                            int(
                                base
                                + min(0.99, float(values[-1]) / 1e6 / max(duration, 0.01)) * span
                            )
                            if values
                            else int(base)
                        )
                        if percent != last:
                            with self.sessions() as db:
                                job = db.get(ProcessingJob, job_id)
                                job.progress_percent = min(percent, 98)
                                db.commit()
                            last = percent
                    except (ValueError, IndexError):
                        pass
                    self.stop_event.wait(0.2)
                if process.returncode:
                    # FFmpeg stderr may include paths or embedded metadata. Persist only sanitized categories.
                    raise HTTPException(
                        422,
                        "FFmpeg could not decode or encode this media. Try a different source or profile.",
                    )
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    def run_job(self, job_id):
        work = storage_path(f"temp/{job_id}-{uuid4().hex}")
        work.mkdir(parents=True, exist_ok=True)
        final_paths = []
        try:
            with self.sessions() as db:
                job = db.get(ProcessingJob, job_id)
                if job is None or job.status != "queued":
                    return
                if job.cancel_requested:
                    job.status = "cancelled"
                    db.commit()
                    return
                if job.attempt_count >= job.max_attempts:
                    job.status = "failed"
                    job.error_code = "attempt_limit"
                    job.error_message = (
                        "Attempt limit reached. Create a new job after checking the source."
                    )
                    job.retryable = False
                    event(db, job, "failed", job.error_message)
                    db.commit()
                    return
                asset = db.get(MediaAsset, job.media_asset_id)
                job.status = "running"
                job.attempt_count += 1
                job.started_at = utcnow()
                job.completed_at = None
                job.progress_percent = 0
                job.error_code = None
                job.error_message = None
                options = dict(job.options)
                source = storage_path(asset.storage_path)
                source_metadata = run_probe(source)
                start = options["trim_start_seconds"]
                end = options.get("trim_end_seconds") or asset.duration_seconds
                duration = end - start
                srt = trimmed_srt(options.get("subtitle_srt", ""), start, end)
                if srt:
                    (work / "captions.srt").write_text(srt)
                event(db, job, "running", "Processing authorized local media.")
                db.commit()
            outputs = []
            for index, profile in enumerate(options["profiles"]):
                if self.cancelled(job_id):
                    raise Cancelled()
                target = work / f"{profile}.mp4"
                vf = filters(
                    profile, source_metadata["width"], source_metadata["height"], options["fps"]
                )
                if options.get("burn_subtitles"):
                    # Generated absolute filename; no user-controlled filter expression.
                    escaped = (
                        str(work / "captions.srt")
                        .replace("\\", "\\\\")
                        .replace(":", "\\:")
                        .replace("'", "'\\''")
                    )
                    vf += f",subtitles=filename='{escaped}'"
                args = [
                    get_settings().ffmpeg_binary,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-ss",
                    str(start),
                    "-i",
                    str(source),
                    "-t",
                    str(duration),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    str(options["crf"]),
                    "-pix_fmt",
                    "yuv420p",
                    "-threads",
                    "2",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-map_metadata",
                    "-1",
                    "-movflags",
                    "+faststart",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                ]
                if options.get("mute_audio"):
                    args += ["-an"]
                elif options.get("normalize_audio"):
                    args += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
                args.append(str(target))
                self.run_command(
                    args,
                    job_id,
                    work,
                    duration,
                    index * 90 / len(options["profiles"]),
                    90 / len(options["profiles"]),
                )
                metadata = run_probe(target)
                expected = {"shorts_1080x1920": (1080, 1920), "shorts_720x1280": (720, 1280)}.get(
                    profile
                )
                if (
                    metadata["video_codec"] != "h264"
                    or (expected and (metadata["width"], metadata["height"]) != expected)
                    or abs(metadata["duration_seconds"] - duration) > max(0.3, 2 / options["fps"])
                ):
                    raise HTTPException(
                        422, "Output validation failed. The file was not published."
                    )
                verify = [
                    get_settings().ffmpeg_binary,
                    "-v",
                    "error",
                    "-xerror",
                    "-nostdin",
                    "-i",
                    str(target),
                    "-f",
                    "null",
                    "-",
                ]
                self.run_command(
                    verify, job_id, work, duration, (index + 1) * 90 / len(options["profiles"]), 0
                )
                relative = f"outputs/{uuid4().hex}.mp4"
                final = storage_path(relative)
                final.parent.mkdir(parents=True, exist_ok=True)
                target.replace(final)
                final_paths.append(final)
                outputs.append(
                    VideoOutput(
                        processing_job_id=job_id,
                        profile=profile,
                        storage_path=relative,
                        filename=f"clip-{job_id[:8]}-{profile}.mp4",
                        size_bytes=final.stat().st_size,
                        sha256=file_hash(final),
                        subtitle_srt=srt,
                        **metadata,
                    )
                )
            with self.sessions() as db:
                job = db.get(ProcessingJob, job_id)
                if job.cancel_requested or self.stop_event.is_set():
                    raise Cancelled()
                db.add_all(outputs)
                job.status = "completed"
                job.progress_percent = 100
                job.completed_at = utcnow()
                event(
                    db, job, "completed", f"{len(outputs)} outputs validated and ready for review."
                )
                db.commit()
            final_paths = []
        except Exception as exc:
            with self.sessions() as db:
                job = db.get(ProcessingJob, job_id)
                if job:
                    if isinstance(exc, Cancelled):
                        job.status = (
                            "queued"
                            if self.stop_event.is_set() and not job.cancel_requested
                            else "cancelled"
                        )
                        message = (
                            "Worker stopped; job retained for restart."
                            if job.status == "queued"
                            else "Cancelled by user."
                        )
                        code = "cancelled"
                    else:
                        job.status = "failed"
                        code = "timeout" if isinstance(exc, TimeoutError) else "processing_failed"
                        message = (
                            exc.detail
                            if isinstance(exc, HTTPException)
                            else "Processing timed out. Retry a shorter clip."
                            if isinstance(exc, TimeoutError)
                            else "Processing failed. Check available storage and FFmpeg installation, then retry."
                        )
                        job.retryable = isinstance(exc, (TimeoutError, OSError))
                        job.error_code = code
                        job.error_message = message
                    job.completed_at = utcnow()
                    event(db, job, job.status, message)
                    db.commit()
        finally:
            for path in final_paths:
                path.unlink(missing_ok=True)
            shutil.rmtree(work, ignore_errors=True)

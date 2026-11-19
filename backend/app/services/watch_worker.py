"""Standalone single-host supervisor. Run: python -m app.services.watch_worker.

OS lock prevents duplicate supervisors; each session has an isolated capture thread.
No raw chat, access tokens, or upstream command output is persisted.
"""

import asyncio
import csv
import fcntl
import shutil
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    DiscoveredItem,
    DiscoverySchedule,
    ProcessingJob,
    WatchMoment,
    WatchSession,
    utcnow,
)
from app.schemas import SearchRequest
from app.schemas.media import JobRequest
from app.services.discovery import discover
from app.services.live_sources import LiveError, TwitchLive, YouTubeLive
from app.services.media import import_upload, run_probe, storage_path
from app.services.spikes import SpikeDetector

STOP = threading.Event()
ACTIVE = {"queued", "waiting", "recording", "reconnecting"}


def update(session_id, **values):
    with SessionLocal() as db:
        row = db.get(WatchSession, session_id)
        for name, value in values.items():
            setattr(row, name, value)
        row.heartbeat_at = utcnow()
        db.commit()


def stopped(session_id):
    if STOP.is_set():
        return True
    with SessionLocal() as db:
        row = db.get(WatchSession, session_id)
        return row is None or row.stop_requested


def pause(session_id, seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if stopped(session_id):
            return
        STOP.wait(min(1, max(0, until - time.monotonic())))


def closed_segments(directory):
    manifest = directory / "segments.csv"
    if not manifest.exists():
        return []
    result = []
    for row in csv.reader(manifest.read_text().splitlines()):
        try:
            name, start, end = row
            path = directory / Path(name).name
            if path.exists() and float(end) > float(start):
                result.append((path, float(start), float(end)))
        except (ValueError, OSError):
            continue
    return result


def space_ok():
    s = get_settings()
    root = s.storage_root.resolve()
    used = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    return (
        used < s.live_storage_gb * 1024**3
        and shutil.disk_usage(root).free > s.live_min_free_gb * 1024**3
    )


class Capture:
    def __init__(self, url, directory):
        s = get_settings()
        self.processes = []
        directory.mkdir(parents=True, exist_ok=True)
        try:
            stream = subprocess.Popen(
                [
                    s.streamlink_binary,
                    "--stdout",
                    "--loglevel",
                    "none",
                    "--stream-timeout",
                    "30",
                    url,
                    "best",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self.processes.append(stream)
            video = subprocess.Popen(
                [
                    s.ffmpeg_binary,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-fflags",
                    "+genpts",
                    "-i",
                    "pipe:0",
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c",
                    "copy",
                    "-f",
                    "segment",
                    "-segment_time",
                    "10",
                    "-segment_list_size",
                    "1000",
                    "-segment_list",
                    str(directory / "segments.csv"),
                    "-reset_timestamps",
                    "1",
                    str(directory / "%06d.ts"),
                ],
                stdin=stream.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.processes.append(video)
            stream.stdout.close()
        except Exception:
            self.close()
            raise

    def alive(self):
        return all(p.poll() is None for p in self.processes)

    def close(self):
        for p in self.processes:
            if p.poll() is None:
                p.terminate()
        for p in self.processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)


def captions(path, directory):
    s = get_settings()
    wav, output = directory / "audio.wav", directory / "captions"
    subprocess.run(
        [
            s.ffmpeg_binary,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        check=True,
        timeout=120,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [s.whisper_binary, "-m", s.whisper_model_path, "-f", str(wav), "-osrt", "-of", str(output)],
        check=True,
        timeout=600,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return output.with_suffix(".srt").read_text()[:100000]


def materialize(session_id, moment_id, directory, segments):
    s = get_settings()
    with SessionLocal() as db:
        row, moment = db.get(WatchSession, session_id), db.get(WatchMoment, moment_id)
        selected = [
            v for v in segments if v[2] > moment.start_seconds and v[1] < moment.end_seconds
        ]
        if (
            not selected
            or selected[0][1] > moment.start_seconds + 1
            or selected[-1][2] < moment.end_seconds - 0.2
            or any(b[1] - a[2] > 0.5 for a, b in zip(selected, selected[1:]))
        ):
            moment.status = "missed_buffer"
            db.commit()
            return
        work = directory / moment.id
        work.mkdir(exist_ok=True)
        listing, clip = work / "concat.txt", work / "clip.mp4"
        # Paths are generated UUID/numeric names, never user-supplied filenames.
        listing.write_text("".join(f"file '{p.resolve()}'\n" for p, _, _ in selected))
        subprocess.run(
            [
                s.ffmpeg_binary,
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-ss",
                str(max(0, moment.start_seconds - selected[0][1])),
                "-t",
                str(moment.end_seconds - moment.start_seconds),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-threads",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(clip),
            ],
            check=True,
            timeout=180,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        probe = run_probe(clip)
        if abs(probe["duration_seconds"] - (moment.end_seconds - moment.start_seconds)) > 0.5:
            raise LiveError("Extracted clip duration does not match the requested window", True)
        upload = SimpleNamespace(
            filename=f"highlight-{moment.id}.mp4", content_type="video/mp4", file=clip.open("rb")
        )
        asset = import_upload(
            db, upload, "creator_authorized", row.authorization_notes, None, row.source_url
        )
        asset.source_provenance = {
            "type": "authorized_live_capture",
            "source_url": row.source_url,
            "creator_id": row.creator_id,
            "creator_name": row.creator_name,
            "watch_session_id": row.id,
            "capture_offset_seconds": moment.start_seconds,
            "timing": "capture-relative estimate; review boundaries before publishing",
        }
        asset.publishing_metadata = {
            "title": f"{row.creator_name} — stream highlight"[:200],
            "description": f"Credit: {row.creator_name}\nSource: {row.source_url}\nCapture offset: {moment.start_seconds:.1f}s",
            "hook": "",
            "hashtags": "",
        }
        if row.options.get("transcribe"):
            try:
                from app.services.media import parse_srt

                text = captions(clip, work)
                parse_srt(text)
                asset.subtitle_srt = text
            except (OSError, subprocess.SubprocessError, ValueError, HTTPException):
                moment.reason += " Caption generation failed; add captions in Media & processing."
        moment.media_asset_id, moment.status = asset.id, "ready"
        if row.options.get("auto_render"):
            options = JobRequest(media_id=asset.id).model_dump(exclude={"media_id"})
            options["subtitle_srt"] = asset.subtitle_srt
            job = ProcessingJob(media_asset_id=asset.id, options=options)
            db.add(job)
            db.flush()
            moment.processing_job_id = job.id
        db.commit()
        shutil.rmtree(work, ignore_errors=True)


def record(session_id, source, row, deadline=None):
    directory = storage_path(f"live/{session_id}/{uuid4().hex}")
    detector = SpikeDetector(
        ratio=row.options["ratio"], minimum=row.options["minimum"], distinct=row.options["distinct"]
    )
    pending = []
    extracting = {}
    anchor = None
    started = time.monotonic()
    last_message_time = 0
    capture = Capture(row.source_url, directory)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clip-extract")
    update(
        session_id,
        status="recording",
        diagnostic="Capturing; detector warms up for five minutes",
        chat_buckets=[],
    )
    try:
        while not stopped(session_id):
            if (
                deadline is not None and time.monotonic() >= deadline
            ) or time.monotonic() - started > row.options["max_hours"] * 3600:
                return
            if not space_ok():
                raise LiveError(
                    "Storage budget or free-space reserve reached; free space before restarting",
                    True,
                )
            segments = closed_segments(directory)
            if not capture.alive():
                raise LiveError("Capture disconnected or ended")
            if not segments and time.monotonic() - started > 90:
                raise LiveError("Capture produced no usable segments")
            # Anchor media time only after the first complete segment. Chat delay is user-calibrated.
            if segments and anchor is None:
                anchor = time.time() - segments[-1][2]
            messages, interval = source.messages()
            buckets = []
            if anchor is not None:
                for timestamp, author, text in sorted(messages):
                    seconds = timestamp - anchor - row.options["chat_delay"]
                    if 0 <= seconds <= time.time() - anchor + 60 and seconds >= last_message_time:
                        buckets.extend(detector.add(seconds, author, text))
                        last_message_time = seconds
                # Allow one polling interval for delayed messages before sealing a bucket.
                buckets.extend(
                    detector.advance(
                        max(0, time.time() - anchor - row.options["chat_delay"] - interval - 2)
                    )
                )
            with SessionLocal() as db:
                current = db.get(WatchSession, session_id)
                current.heartbeat_at = utcnow()
                current.chat_buckets = (current.chat_buckets + [asdict(b) for b in buckets])[-180:]
                for b in buckets:
                    if not b.spike:
                        continue
                    moment = WatchMoment(
                        watch_session_id=session_id,
                        start_seconds=max(0, b.start - row.options["pre_roll"]),
                        end_seconds=b.start + 10 + row.options["post_roll"],
                        reason=f"{b.count} messages / {b.authors} chatters; baseline {b.baseline:.1f} per 10s",
                    )
                    db.add(moment)
                    db.flush()
                    pending.append((moment.id, moment.start_seconds, moment.end_seconds))
                db.commit()
            latest = segments[-1][2] if segments else 0
            for item in pending[:]:
                mid, _, end = item
                if latest >= end and mid not in extracting and len(extracting) < 4:
                    extracting[mid] = executor.submit(
                        materialize, session_id, mid, directory, segments
                    )
                future = extracting.get(mid)
                if future and future.done():
                    if future.exception():
                        with SessionLocal() as db:
                            moment = db.get(WatchMoment, mid)
                            moment.status = "failed"
                            moment.reason += " Clip extraction failed; inspect source availability."
                            db.commit()
                    del extracting[mid]
                    pending.remove(item)
            keep_from = min([latest - 600] + [p[1] for p in pending])
            for path, _, end in segments:
                if end < keep_from:
                    path.unlink(missing_ok=True)
            pause(session_id, interval)
    finally:
        capture.close()
        executor.shutdown(wait=True, cancel_futures=True)
        with SessionLocal() as db:
            for mid, _, _ in pending:
                moment = db.get(WatchMoment, mid)
                if moment.status == "pending":
                    moment.status = "incomplete"
                    moment.reason += " Capture stopped before the full clip window was available."
            db.commit()
        shutil.rmtree(directory, ignore_errors=True)


def watch(session_id):
    source = None
    try:
        with SessionLocal() as db:
            row = db.get(WatchSession, session_id)
        s = get_settings()
        if not shutil.which(s.streamlink_binary) or not shutil.which(s.ffmpeg_binary):
            raise LiveError("Install Streamlink and FFmpeg on the watcher server", True)
        if row.options.get("transcribe") and (
            not Path(s.whisper_model_path).is_file() or not shutil.which(s.whisper_binary)
        ):
            raise LiveError(
                "Configure a local whisper.cpp executable and model, or disable automatic captions",
                True,
            )
        source_type = YouTubeLive if row.platform == "youtube" else TwitchLive
        deadline = time.monotonic() + row.options["max_hours"] * 3600
        retries = 0
        update(session_id, started_at=utcnow())
        while not stopped(session_id) and time.monotonic() < deadline:
            try:
                source = source_type(row)
                update(
                    session_id,
                    status="waiting",
                    diagnostic="Waiting for the authorized creator to go live",
                )
                while not source.live() and not stopped(session_id) and time.monotonic() < deadline:
                    update(session_id, status="waiting")
                    pause(session_id, 30)
                if stopped(session_id) or time.monotonic() >= deadline:
                    break
                record(session_id, source, row, deadline)
                break
            except (LiveError, OSError) as exc:
                if isinstance(exc, LiveError) and exc.terminal:
                    raise
                retries += 1
                if retries > 5:
                    raise LiveError(
                        "Reconnect limit reached. Check stream availability and start a new watch.",
                        True,
                    ) from None
                update(
                    session_id,
                    status="reconnecting",
                    reconnects=retries,
                    diagnostic="Connection interrupted; retrying. New capture starts a fresh detector baseline.",
                )
                pause(session_id, min(120, 5 * 2**retries))
            finally:
                if source:
                    source.close()
        with SessionLocal() as db:
            user_stopped = db.get(WatchSession, session_id).stop_requested
        resume = STOP.is_set() and not user_stopped
        update(
            session_id,
            status="queued" if resume else "stopped" if user_stopped else "completed",
            ended_at=None if resume else utcnow(),
            diagnostic="Paused for worker restart" if resume else "Watch finished",
        )
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, LiveError)
            else "Watcher failed. Check configuration and available disk space."
        )
        update(session_id, status="failed", ended_at=utcnow(), diagnostic=message)


async def run_schedule(schedule_id):
    with SessionLocal() as db:
        row = db.get(DiscoverySchedule, schedule_id)
        # Reserve the next run before the network call, preventing tight retry loops after crashes.
        row.next_run_at = utcnow() + timedelta(minutes=row.interval_minutes)
        row.last_run_at = utcnow()
        db.commit()
        try:
            result = await discover(
                db,
                SearchRequest(
                    query=row.query, platforms=row.platforms, limit=50, sort="engagement"
                ),
                "live",
            )
            count = 0
            for item in result.items:
                if item.creator_id in row.creator_ids:
                    db.get(DiscoveredItem, item.id).saved = True
                    count += 1
            row.diagnostic = f"Saved {count} matching creator results; source file required for metadata-only items."
            if result.warnings:
                row.diagnostic += " " + " ".join(result.warnings)
            db.commit()
        except Exception:
            db.rollback()
            row = db.get(DiscoverySchedule, schedule_id)
            row.diagnostic = (
                "Scheduled search failed; check Integrations. Next interval remains scheduled."
            )
            db.commit()


def main():
    root = get_settings().storage_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".watcher.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A watcher supervisor is already running") from None
        signal.signal(signal.SIGTERM, lambda *_: STOP.set())
        signal.signal(signal.SIGINT, lambda *_: STOP.set())
        with SessionLocal() as db:
            for row in db.scalars(
                select(WatchSession).where(WatchSession.status.in_(ACTIVE - {"queued"}))
            ):
                row.status = "queued"
                row.diagnostic = "Recovered after worker restart; starting a new capture timeline"
            for moment in db.scalars(select(WatchMoment).where(WatchMoment.status == "pending")):
                moment.status = "incomplete"
                moment.reason += " Worker restarted before extraction completed."
            db.commit()
        # Only ephemeral live buffers are removed; imported clips and outputs remain untouched.
        shutil.rmtree(root / "live", ignore_errors=True)
        threads = {}
        try:
            while not STOP.is_set():
                threads = {k: v for k, v in threads.items() if v.is_alive()}
                with SessionLocal() as db:
                    queued = list(
                        db.scalars(
                            select(WatchSession)
                            .where(
                                WatchSession.status == "queued",
                                WatchSession.stop_requested.is_(False),
                            )
                            .order_by(WatchSession.created_at)
                        )
                    )
                    schedules = list(
                        db.scalars(
                            select(DiscoverySchedule.id).where(
                                DiscoverySchedule.enabled.is_(True),
                                DiscoverySchedule.next_run_at <= utcnow(),
                            )
                        )
                    )
                for row in queued:
                    if len(threads) >= get_settings().live_max_sessions:
                        break
                    if row.id not in threads:
                        t = threading.Thread(target=watch, args=(row.id,), daemon=True)
                        threads[row.id] = t
                        t.start()
                for schedule_id in schedules:
                    if not STOP.is_set():
                        asyncio.run(run_schedule(schedule_id))
                STOP.wait(2)
        finally:
            STOP.set()
            for t in threads.values():
                t.join()


if __name__ == "__main__":
    main()

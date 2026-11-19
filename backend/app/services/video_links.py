"""Bounded public-video retrieval; no cookies, playlist expansion or DRM bypass."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse

from app.core.config import get_settings


class LinkError(Exception):
    pass


class LinkCancelled(LinkError):
    pass


def normalize_url(value):
    try:
        p = urlparse(value)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            raise ValueError()
    except ValueError:
        raise ValueError(
            "Use a public HTTPS YouTube video, Twitch clip or Twitch recording URL"
        ) from None
    host = (p.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        video = p.path.strip("/") if host == "youtu.be" else parse_qs(p.query).get("v", [""])[0]
        if p.path.startswith(("/shorts/", "/live/")):
            video = p.path.split("/")[2]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            return "https://www.youtube.com/watch?v=" + video
    if host == "clips.twitch.tv" and re.fullmatch(r"/[A-Za-z0-9_-]{5,150}", p.path):
        return "https://clips.twitch.tv" + p.path
    if host in {"twitch.tv", "www.twitch.tv"} and re.fullmatch(
        r"/(videos/[0-9]+|[A-Za-z0-9_]+/clip/[A-Za-z0-9_-]{5,150})", p.path
    ):
        return "https://www.twitch.tv" + p.path
    raise ValueError(
        "Paste one YouTube video, Twitch clip or Twitch recording; channel and playlist URLs are not supported"
    )


def run_bounded(args, work, stopped=lambda: False, timeout=120, max_bytes=None):
    work.mkdir(parents=True, exist_ok=True)
    limit = max_bytes or get_settings().max_upload_mb * 1024**2 * 2
    log = work / "command-output.txt"
    with log.open("wb") as out:
        proc = subprocess.Popen(
            args,
            stdout=out,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if stopped():
                    raise LinkCancelled("Cancelled")
                if time.monotonic() > deadline:
                    raise LinkError("Operation timed out; try a shorter video")
                total = sum(p.stat().st_size for p in work.rglob("*") if p.is_file())
                if (
                    total > limit
                    or shutil.disk_usage(work).free < get_settings().live_min_free_gb * 1024**3
                ):
                    raise LinkError("Download exceeded the size limit or free disk reserve")
                time.sleep(0.2)
            if stopped():
                raise LinkCancelled("Cancelled")
            if sum(p.stat().st_size for p in work.rglob("*") if p.is_file()) > limit:
                raise LinkError("Download exceeded the size limit")
            if proc.returncode:
                raise LinkError(
                    "Source unavailable, restricted, or unsupported by the downloader. Upload your source file instead."
                )
            if log.stat().st_size > 8 * 1024**2:
                raise LinkError("Source metadata exceeds the supported limit")
            return log.read_text(errors="replace")
        finally:
            # Also terminate any transcoder descendants, including on cancellation.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)
            log.unlink(missing_ok=True)


def base_args():
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-playlist",
        "--no-cache-dir",
        "--no-progress",
        "--socket-timeout",
        "15",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--js-runtimes",
        "node",
    ]


def inspect_video(url, work, stopped=lambda: False):
    raw = run_bounded(
        base_args() + ["--dump-single-json", "--skip-download", normalize_url(url)], work, stopped
    )
    try:
        info = json.loads(raw)
    except ValueError:
        raise LinkError("Could not read source metadata") from None
    if (
        info.get("_type") in {"playlist", "multi_video"}
        or info.get("is_live")
        or info.get("live_status") in {"is_live", "is_upcoming"}
    ):
        raise LinkError(
            "This page handles finished recordings. Use Live Watch for an active or upcoming stream."
        )
    duration = info.get("duration") or 0
    if not 0 < duration <= get_settings().link_max_duration_seconds:
        raise LinkError("Recording duration is missing or exceeds the configured limit")
    return info


def fetch_video(url, work, stopped=lambda: False, sample=False, info=None):
    s = get_settings()
    args = base_args() + [
        "-f",
        "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]",
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "--max-filesize",
        str(s.max_upload_mb * 1024**2),
        "--ffmpeg-location",
        shutil.which(s.ffmpeg_binary) or s.ffmpeg_binary,
    ]
    if sample:
        duration = float(info["duration"])
        args += ["--force-keyframes-at-cuts"]
        args += ["-o", str(work / "sample-%(section_start)s.%(ext)s")]
        for fraction in (0.15, 0.5, 0.85):
            start = max(0, duration * fraction - 2)
            args += ["--download-sections", f"*{start:.3f}-{min(duration, start + 4):.3f}"]
    else:
        args += ["-o", str(work / "source.%(ext)s")]
    run_bounded(
        args + [normalize_url(url)],
        work,
        stopped,
        timeout=180 if sample else s.link_download_timeout_seconds,
        max_bytes=150 * 1024**2 if sample else None,
    )
    files = sorted(work.glob("sample-*.mp4" if sample else "source.mp4"))
    if not files:
        raise LinkError("No downloadable video was returned")
    return files


def fetch_chat(url, work, stopped=lambda: False):
    work = work / "chat"
    try:
        run_bounded(
            base_args()
            + [
                "--skip-download",
                "--write-subs",
                "--sub-langs",
                "live_chat",
                "-o",
                str(work / "replay.%(ext)s"),
                normalize_url(url),
            ],
            work,
            stopped,
            timeout=180,
            max_bytes=100 * 1024**2,
        )
    except LinkCancelled:
        raise
    except LinkError:
        return None
    return next(work.glob("*.live_chat.json"), None)


def sampled_faces(files):
    import cv2

    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    read, hits = 0, 0
    overlay_positions = []
    for section, path in enumerate(files):
        capture = cv2.VideoCapture(str(path))
        try:
            total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            for fraction in (0.15, 0.5, 0.85):
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(total * fraction))
                ok, frame = capture.read()
                if not ok:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (640, max(2, round(gray.shape[0] * 640 / gray.shape[1]))))
                read += 1
                faces = detector.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24)
                )
                if len(faces):
                    hits += 1
                h, w = gray.shape
                for x, y, fw, fh in faces:
                    cx, cy = (x + fw / 2) / w, (y + fh / 2) / h
                    # A stable small edge overlay is more likely a facecam than an NPC/cutscene face.
                    if fw * fh / (w * h) < 0.12 and (
                        cx < 0.3 or cx > 0.7 or cy < 0.25 or cy > 0.75
                    ):
                        overlay_positions.append((section, cx, cy))
        finally:
            capture.release()
    if read < 6:
        return "unknown", f"Only {read} sampled frames were readable"
    stable = any(
        len(
            {
                other
                for other, ox, oy in overlay_positions
                if abs(ox - x) < 0.08 and abs(oy - y) < 0.08
            }
        )
        >= 2
        for _, x, y in overlay_positions
    )
    category = "face" if stable else "faceless" if hits == 0 else "unknown"
    return category, (
        f"Face-like shapes in {hits}/{read} sampled frames; "
        f"stable facecam-like overlay: {'yes' if stable else 'no'}. Automatic estimate; not identity verification."
    )

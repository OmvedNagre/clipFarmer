import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.models import MediaAsset

AUTHORIZED = {"user_owned", "creator_authorized", "licensed"}
EXTENSIONS = {
    ".mp4": {"video/mp4", "application/mp4"},
    ".mov": {"video/quicktime"},
    ".m4v": {"video/mp4", "video/x-m4v"},
    ".webm": {"video/webm"},
    ".mkv": {"video/x-matroska"},
}


def storage_path(relative):
    root = get_settings().storage_root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(400, "Invalid storage identifier")
    return target


def run_probe(path):
    try:
        p = subprocess.run(
            [
                get_settings().ffprobe_binary,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        data = json.loads(p.stdout)
        videos = [
            s
            for s in data["streams"]
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ]
        video = videos[0]
        duration = float(data["format"].get("duration") or video.get("duration") or 0)
        width, height = int(video["width"]), int(video["height"])
        ratio = video.get("sample_aspect_ratio", "1:1")
        if ratio and ratio != "N/A":
            numerator, denominator = map(int, ratio.split(":"))
            if numerator > 0 and denominator > 0:
                width = round(width * numerator / denominator)
        rotation = int(
            next(
                (s.get("rotation", 0) for s in video.get("side_data_list", []) if "rotation" in s),
                0,
            )
        )
        if abs(rotation) % 180 == 90:
            width, height = height, width
        audio = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
        if (
            not math.isfinite(duration)
            or not 0 < duration <= 86400
            or not 2 <= width <= 8192
            or not 2 <= height <= 8192
        ):
            raise ValueError("invalid dimensions or duration")
        return {
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "video_codec": video["codec_name"],
            "audio_codec": audio["codec_name"] if audio else None,
        }
    except FileNotFoundError:
        raise HTTPException(503, "FFprobe is missing. Install FFmpeg and restart.") from None
    except (subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(
            422, "The file is corrupt, unsupported, or has invalid video metadata."
        ) from None


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate_signature(path, ext):
    with path.open("rb") as f:
        header = f.read(32)
    valid = (
        (header[4:8] == b"ftyp" or header[4:8] in {b"moov", b"mdat", b"wide"})
        if ext in {".mp4", ".mov", ".m4v"}
        else header[:4] == b"\x1a\x45\xdf\xa3"
    )
    if not valid:
        raise HTTPException(422, "File signature does not match a supported video container.")


def import_upload(db, upload, authorization, notes, item_id, source_url):
    settings = get_settings()
    original = Path((upload.filename or "video").replace("\\", "/")).name[:240]
    ext = Path(original).suffix.lower()
    if ext not in EXTENSIONS or upload.content_type not in EXTENSIONS[ext] | {
        "application/octet-stream"
    }:
        raise HTTPException(
            415, "Upload an MP4, MOV, M4V, WebM or MKV video with its matching content type."
        )
    token = uuid4().hex
    incoming = storage_path(f"incoming/{token}{ext}")
    incoming.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = 0
        with incoming.open("wb") as target:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(
                        413, f"File exceeds the {settings.max_upload_mb} MB upload limit."
                    )
                target.write(chunk)
        validate_signature(incoming, ext)
        metadata = run_probe(incoming)
        digest = file_hash(incoming)
        existing = db.scalar(select(MediaAsset).where(MediaAsset.sha256 == digest))
        if existing:
            return existing
        relative = f"originals/{token}{ext}"
        final = storage_path(relative)
        final.parent.mkdir(parents=True, exist_ok=True)
        incoming.replace(final)
        asset = MediaAsset(
            discovered_item_id=item_id,
            original_filename=original,
            stored_filename=final.name,
            storage_path=relative,
            mime_type="video/mp4"
            if ext in {".mp4", ".m4v"}
            else next(iter(sorted(EXTENSIONS[ext]))),
            size_bytes=size,
            sha256=digest,
            **metadata,
            authorization_status=authorization,
            authorization_notes=notes,
            source_provenance={
                "type": "user_upload",
                "source_url": source_url or None,
                "original_name": original,
            },
        )
        try:
            db.add(asset)
            db.commit()
        except IntegrityError:
            db.rollback()
            final.unlink(missing_ok=True)
            asset = db.scalar(select(MediaAsset).where(MediaAsset.sha256 == digest))
            if not asset:
                raise HTTPException(409, "Import conflict. Try again.") from None
        return asset
    finally:
        incoming.unlink(missing_ok=True)
        upload.file.close()


def parse_srt(text):
    if not text.strip():
        return []
    cues = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r", "")):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if len(lines) < 2:
            raise HTTPException(422, "Invalid SRT: every cue needs a timestamp and text.")
        match = re.fullmatch(
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})", lines[0].strip()
        )
        if not match:
            raise HTTPException(422, "Use SRT timestamps: 00:00:01,000 --> 00:00:03,000")
        v = list(map(int, match.groups()))
        start = v[0] * 3600 + v[1] * 60 + v[2] + v[3] / 1000
        end = v[4] * 3600 + v[5] * 60 + v[6] + v[7] / 1000
        if end <= start or any(v[i] >= 60 for i in (1, 2, 5, 6)):
            raise HTTPException(422, "Invalid SRT cue timing.")
        # Plain text only: do not pass ASS override commands to libass.
        content = re.sub(r"<[^>]*>|\{[^}]*\}", "", "\n".join(lines[1:])).replace("\\", "")
        cues.append((start, end, content))
    return cues


def trimmed_srt(text, start, end):
    def stamp(t):
        ms = round(t * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"

    result = []
    for a, b, content in parse_srt(text):
        a, b = max(a, start) - start, min(b, end) - start
        if b > a:
            result.append(f"{len(result) + 1}\n{stamp(a)} --> {stamp(b)}\n{content}")
    return "\n\n".join(result) + "\n" if result else ""

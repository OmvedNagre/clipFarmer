"""Measured chat/replay peaks and explicitly labelled audio-only suggestions."""

import array
import json
import math
from collections import defaultdict

from app.core.config import get_settings
from app.services.video_links import run_bounded


def choose_moments(candidates, duration, limit=10):
    chosen = []
    for item in sorted(candidates, key=lambda x: x["score"], reverse=True):
        t = max(0, min(duration, item["time"]))
        start, end = max(0, t - 30), min(duration, t + 15)
        if end - start < 5 or any(start < x["end"] and end > x["start"] for x in chosen):
            continue
        chosen.append({**item, "start": round(start, 2), "end": round(end, 2), "time": round(t, 2)})
        if len(chosen) == limit:
            break
    return chosen


def replay_peaks(path, duration):
    buckets = defaultdict(lambda: defaultdict(set))
    seen = set()
    with path.open() as f:
        for line in f:
            if len(line) > 2_000_000:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            stack = [(data, None)]
            while stack:
                value, offset = stack.pop()
                if isinstance(value, dict):
                    if "videoOffsetTimeMsec" in value:
                        try:
                            offset = float(value["videoOffsetTimeMsec"]) / 1000
                        except (ValueError, TypeError):
                            continue
                    for key in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
                        msg = value.get(key)
                        if msg and offset is not None and 0 <= offset <= duration:
                            identity = msg.get("id")
                            author = msg.get("authorExternalChannelId")
                            text = "".join(
                                x.get("text", "") for x in msg.get("message", {}).get("runs", [])
                            ).casefold()
                            if identity and identity not in seen and author:
                                seen.add(identity)
                                slot = buckets[int(offset // 10)][author]
                                if len(slot) < 3:
                                    slot.add(text[:500])
                    stack.extend((v, offset) for v in value.values() if isinstance(v, (dict, list)))
                elif isinstance(value, list):
                    stack.extend((v, offset) for v in value)
    counts = {i: sum(len(v) for v in authors.values()) for i, authors in buckets.items()}
    candidates = []
    for i, count in counts.items():
        baseline = sum(counts.get(k, 0) for k in range(max(0, i - 30), i)) / max(1, min(i, 30))
        authors = len(buckets[i])
        if count >= 3 and authors >= 2:
            candidates.append(
                {
                    "time": i * 10 + 5,
                    "score": round(count * math.log2(2 + authors), 3),
                    "method": "chat_replay",
                    "evidence": f"{count} deduplicated messages from {authors} chatters / 10s; prior baseline {baseline:.1f}",
                }
            )
    return choose_moments(candidates, duration)


def heatmap_peaks(info, duration):
    candidates = []
    for point in info.get("heatmap") or []:
        try:
            score = float(point["value"])
            t = (float(point["start_time"]) + float(point["end_time"])) / 2
            if math.isfinite(score) and math.isfinite(t) and score > 0:
                candidates.append(
                    {
                        "time": t,
                        "score": score,
                        "method": "replay_heatmap",
                        "evidence": "Platform replay-intensity data; not a live viewer count",
                    }
                )
        except (KeyError, ValueError, TypeError):
            continue
    return choose_moments(candidates, duration)


def audio_peaks(path, work, duration, stopped=lambda: False):
    pcm = work / "analysis.pcm"
    run_bounded(
        [
            get_settings().ffmpeg_binary,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            str(pcm),
        ],
        work,
        stopped,
        timeout=600,
    )
    energies = []
    try:
        with pcm.open("rb") as f:
            while chunk := f.read(16000):
                values = array.array("h")
                values.frombytes(chunk[: len(chunk) // 2 * 2])
                energies.append(math.sqrt(sum(v * v for v in values) / max(1, len(values))) / 32768)
        candidates = []
        for i in range(5, len(energies) - 1):
            baseline = sum(energies[max(0, i - 60) : i]) / min(i, 60)
            if (
                energies[i] > max(0.025, baseline * 1.8)
                and energies[i] >= energies[i - 1]
                and energies[i] >= energies[i + 1]
            ):
                candidates.append(
                    {
                        "time": i,
                        "score": round(energies[i] / max(0.005, baseline), 3),
                        "method": "audio_energy",
                        "evidence": "Audio-energy increase only; audience engagement data was unavailable",
                    }
                )
        return choose_moments(candidates, duration)
    finally:
        pcm.unlink(missing_ok=True)

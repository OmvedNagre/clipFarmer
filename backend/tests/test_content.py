import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import get_settings
from app.models import DailyFeedItem, DailyFeedRun
from app.services import daily_feed, link_jobs
from app.services.daily_feed import gameplay_match, next_midnight, reserve_run
from app.services.link_jobs import ContentWorker
from app.services.recording_peaks import choose_moments, heatmap_peaks, replay_peaks
from app.services.video_links import LinkCancelled, normalize_url, run_bounded, sampled_faces

URL = "https://www.youtube.com/watch?v=Z0CPIt32Ux0"


@pytest.mark.parametrize(
    "title",
    [
        "GTA VI official trailer gameplay",
        "GTA 6 gameplay news",
        "GTA V mod GTA 6 gameplay",
        "GTA 6 leaked gameplay",
        "GTA VI gameplay concept",
        "GTA 6 release date gameplay",
        "GTA 6 trailer reaction",
        "GTA 5 walkthrough",
        "New GTA 6 Gameplay Was on South Park!",
        "GTAVI Funny Superheroes Gameplay",
        "Reacciona al Gameplay de GTA 6",
    ],
)
def test_gameplay_filter_excludes_filler(title):
    assert not gameplay_match(title)


def test_gameplay_filter_and_ist_rollover():
    assert gameplay_match("GTA VI gameplay walkthrough mission 1")
    assert gameplay_match("Grand Theft Auto 6 gameplay with a facecam")
    assert not gameplay_match("GTA VI news")
    assert next_midnight(datetime(2026, 11, 17, 18, 29, tzinfo=UTC)) == datetime(
        2026, 11, 17, 18, 30, tzinfo=UTC
    )
    assert next_midnight(datetime(2026, 11, 17, 18, 30, tzinfo=UTC)) == datetime(
        2026, 11, 18, 18, 30, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/a.mp4",
        "https://youtube.com.evil/watch?v=Z0CPIt32Ux0",
        "https://youtube.com/playlist?list=foo",
        "https://user:secret@youtube.com/watch?v=Z0CPIt32Ux0",
        "https://twitch.tv/channel",
        "file:///etc/passwd",
    ],
)
def test_link_url_restrictions(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_normalizes_single_video_urls():
    assert normalize_url("https://youtu.be/Z0CPIt32Ux0?list=secret") == URL
    assert normalize_url("https://youtube.com/shorts/Z0CPIt32Ux0") == URL
    assert normalize_url("https://twitch.tv/videos/123456") == "https://www.twitch.tv/videos/123456"


def test_own_stream_has_no_permission_gate(client):
    http, _ = client
    response = http.post("/api/v1/links", json={"source_url": URL, "mode": "stream"})
    assert response.status_code == 201
    assert response.json()["authorization"] == "user_owned"
    assert http.post("/api/v1/links", json={"source_url": URL, "mode": "stream"}).status_code == 409
    assert http.post("/api/v1/links", json={"source_url": URL, "mode": "video"}).status_code == 422
    assert (
        http.post(
            "/api/v1/links", json={"source_url": URL, "mode": "video", "permission_confirmed": True}
        ).status_code
        == 201
    )
    assert http.get(f"/api/v1/links/{response.json()['id']}/download").status_code == 409
    http.post(f"/api/v1/links/{response.json()['id']}/cancel")
    assert http.get("/api/v1/links").json()[-1]["status"] == "cancelled"


def test_feed_single_run_per_ist_day_and_auth(client, monkeypatch):
    http, _ = client
    feed = http.get("/api/v1/daily-feed").json()
    assert feed["limit"] == 20 and feed["timezone"] == "Asia/Kolkata"
    assert http.post("/api/v1/daily-feed/run").status_code == 201
    assert http.post("/api/v1/daily-feed/run").status_code == 409
    monkeypatch.setattr(get_settings(), "app_access_token", SecretStr("private"))
    assert http.get("/api/v1/links").status_code == 401
    assert http.get("/api/v1/daily-feed").status_code == 401


def replay_line(offset, identity, author, text="wow"):
    return {
        "replayChatItemAction": {
            "videoOffsetTimeMsec": str(offset * 1000),
            "actions": [
                {
                    "addChatItemAction": {
                        "item": {
                            "liveChatTextMessageRenderer": {
                                "id": identity,
                                "authorExternalChannelId": author,
                                "message": {"runs": [{"text": text}]},
                            }
                        }
                    }
                }
            ],
        }
    }


def test_chat_replay_peaks_dedup_and_non_overlap(tmp_path):
    path = tmp_path / "chat.json"
    rows = [replay_line(120 + i % 5, str(i), f"user{i % 10}", f"reaction{i}") for i in range(30)]
    rows += rows + [
        replay_line(300 + i % 5, "spam" + str(i), "spammer", str(i)) for i in range(100)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    moments = replay_peaks(path, 600)
    assert len(moments) == 1 and moments[0]["method"] == "chat_replay"
    assert moments[0]["time"] == 125 and "30 deduplicated" in moments[0]["evidence"]
    selected = choose_moments(
        [{"time": 100, "score": 5}, {"time": 110, "score": 10}, {"time": 500, "score": 1}], 600
    )
    assert [m["time"] for m in selected] == [110, 500]


def test_heatmap_signal_is_named_honestly():
    moments = heatmap_peaks({"heatmap": [{"start_time": 100, "end_time": 110, "value": 0.9}]}, 600)
    assert moments[0]["method"] == "replay_heatmap"
    assert "not a live viewer count" in moments[0]["evidence"]
    assert heatmap_peaks({}, 600) == []


def test_subprocess_cancellation(tmp_path):
    with pytest.raises(LinkCancelled):
        run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, lambda: True)
    assert not (tmp_path / "command-output.txt").exists()


def candidate(i):
    return SimpleNamespace(
        external_id=f"video{i}",
        canonical_url=URL,
        title=f"GTA VI gameplay mission {i}",
        creator_id="not_authorized",
        raw_metadata={"license": "youtube"},
        model_dump=lambda **kw: {
            "title": f"GTA VI gameplay {i}",
            "creator_name": "Creator",
            "creator_id": "not_authorized",
            "view_count": 1000 - i,
            "canonical_url": URL,
        },
    )


def test_daily_cap_balance_duplicates_and_summary(client, monkeypatch):
    _, factory = client
    with factory() as db:
        rid = reserve_run(db)

    async def search():
        return [candidate(i) for i in range(60)]

    monkeypatch.setattr(daily_feed, "discover_candidates", search)
    monkeypatch.setattr(
        daily_feed, "inspect_video", lambda *a, **kw: {"title": "GTA VI gameplay", "duration": 100}
    )
    monkeypatch.setattr(daily_feed, "fetch_video", lambda *a, **kw: [Path("unused")])
    calls = []

    def classify(files):
        n = len(calls)
        calls.append(1)
        return ("face" if n % 2 else "faceless"), "sampled frames"

    monkeypatch.setattr(daily_feed, "sampled_faces", classify)
    sent = []
    monkeypatch.setattr(
        daily_feed,
        "telegram",
        lambda method, payload, file=None: sent.append((method, payload)) or ("sent", "Delivered"),
    )
    daily_feed.run_feed(factory, rid)
    with factory() as db:
        rows = list(db.scalars(select(DailyFeedItem)))
        assert len(rows) == 20 and sum(r.category == "face" for r in rows) == 10
        assert all(
            r.link_status == "sent" and r.attachment_status == "not_authorized" for r in rows
        )
        assert db.get(DailyFeedRun, rid).summary_status == "sent"
        second = DailyFeedRun(day="2099-01-01")
        db.add(second)
        db.commit()
        second_id = second.id
    assert len(sent) == 21
    daily_feed.run_feed(factory, second_id)
    with factory() as db:
        rows = list(db.scalars(select(DailyFeedItem)))
        assert len(rows) == 40 and len({r.video_id for r in rows}) == 40


def test_uncertain_delivery_is_not_automatically_retried(client, monkeypatch):
    _, factory = client
    with factory() as db:
        rid = reserve_run(db)
        item = DailyFeedItem(
            run_id=rid,
            video_id="v",
            snapshot={**candidate(1).model_dump(), "classification": "sampled frames"},
            category="face",
            attachment_status="not_authorized",
        )
        db.add(item)
        db.commit()
        iid = item.id
    sent = []
    monkeypatch.setattr(
        daily_feed, "telegram", lambda *a, **kw: sent.append(1) or ("unknown", "Timeout")
    )
    daily_feed.deliver_item(factory, iid)
    daily_feed.deliver_item(factory, iid)
    assert len(sent) == 1


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            get_settings().ffmpeg_binary,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=30",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=20,
    )
    return path


def test_link_stream_real_import_render_download_without_approval(client, monkeypatch, video):
    http, factory = client
    monkeypatch.setattr(
        link_jobs,
        "inspect_video",
        lambda *a, **kw: {"title": "My recording", "duration": 4, "uploader": "Me"},
    )

    def fetch(url, work, stopped):
        work.mkdir(parents=True, exist_ok=True)
        target = work / "source.mp4"
        shutil.copyfile(video, target)
        return [target]

    monkeypatch.setattr(link_jobs, "fetch_video", fetch)
    monkeypatch.setattr(link_jobs, "fetch_chat", lambda *a, **kw: None)
    monkeypatch.setattr(link_jobs, "audio_peaks", lambda *a, **kw: [])
    row = http.post("/api/v1/links", json={"source_url": URL, "mode": "stream"}).json()
    ContentWorker(factory).run_link(row["id"])
    result = http.get("/api/v1/links").json()[0]
    assert result["status"] == "ready" and "No reliable peaks" in result["progress"]
    assert http.get(f"/api/v1/links/{row['id']}/download").status_code == 200
    job = http.post(
        f"/api/v1/links/{row['id']}/clip", json={"start": 0.5, "end": 2.5, "profile": "original"}
    )
    assert job.status_code == 201
    from app.services.processing import Worker

    Worker(factory).run_job(job.json()["id"])
    outputs = http.get(f"/api/v1/processing/jobs/{job.json()['id']}/outputs").json()
    assert len(outputs) == 1
    assert http.get(f"/api/v1/outputs/{outputs[0]['id']}/download").status_code == 200
    assert (
        http.post(f"/api/v1/links/{row['id']}/clip", json={"start": 2, "end": 1}).status_code == 422
    )


def test_actual_frame_sampler_runs(video):
    category, evidence = sampled_faces([video, video, video])
    assert category in {"face", "faceless", "unknown"} and "9 sampled frames" in evidence


def test_audio_fallback_detects_burst_and_labels_it(tmp_path):
    from app.services.recording_peaks import audio_peaks

    path = tmp_path / "sound.wav"
    subprocess.run(
        [
            get_settings().ffmpeg_binary,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=if(between(t\\,30\\,32)\\,0.7\\,0.005)*sin(2*PI*440*t):s=8000:d=70",
            str(path),
        ],
        check=True,
        timeout=20,
    )
    moments = audio_peaks(path, tmp_path, 70)
    assert moments and moments[0]["method"] == "audio_energy"
    assert 29 <= moments[0]["time"] <= 33
    assert "audience engagement data was unavailable" in moments[0]["evidence"]


def test_quiet_audio_has_no_fabricated_peak(tmp_path):
    from app.services.recording_peaks import audio_peaks

    path = tmp_path / "silence.wav"
    subprocess.run(
        [
            get_settings().ffmpeg_binary,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "10",
            str(path),
        ],
        check=True,
        timeout=20,
    )
    assert audio_peaks(path, tmp_path, 10) == []


def test_chat_download_uses_its_own_size_budget(tmp_path, monkeypatch):
    from app.services import video_links

    (tmp_path / "source.mp4").write_bytes(b"retained source")

    def fake_run(args, work, *a, **kw):
        assert work == tmp_path / "chat"
        work.mkdir(parents=True, exist_ok=True)
        (work / "replay.live_chat.json").write_text("{}")

    monkeypatch.setattr(video_links, "run_bounded", fake_run)
    assert video_links.fetch_chat(URL, tmp_path).name == "replay.live_chat.json"


def test_authorized_attachment_and_cleanup(client, monkeypatch, video):
    _, factory = client
    with factory() as db:
        rid = reserve_run(db)
        snapshot = {
            **candidate(1).model_dump(),
            "classification": "sampled",
            "license": "creativeCommon",
        }
        item = DailyFeedItem(
            run_id=rid,
            video_id="attachment",
            snapshot=snapshot,
            category="face",
            attachment_status="pending",
        )
        db.add(item)
        db.commit()
        iid = item.id
    monkeypatch.setattr(
        daily_feed, "inspect_video", lambda *a, **kw: {"channel_id": "not_authorized"}
    )

    def fetch(url, work, stopped):
        work.mkdir(parents=True, exist_ok=True)
        target = work / "source.mp4"
        shutil.copyfile(video, target)
        return [target]

    monkeypatch.setattr(daily_feed, "fetch_video", fetch)
    sent = []
    monkeypatch.setattr(
        daily_feed,
        "telegram",
        lambda method, *a, **kw: sent.append(method) or ("sent", "Delivered"),
    )
    daily_feed.deliver_item(factory, iid)
    assert sent == ["sendMessage", "sendVideo"]
    daily_feed.deliver_item(factory, iid)
    assert len(sent) == 2
    assert not (get_settings().storage_root / "daily-downloads" / iid).exists()


def test_content_worker_recovers_without_duplicate_delivery(client, monkeypatch):
    from app.models import LinkImport

    _, factory = client
    with factory() as db:
        rid = reserve_run(db)
        run = db.get(DailyFeedRun, rid)
        run.status = "running"
        run.summary_status = "sending"
        row = LinkImport(
            source_url=URL, mode="stream", authorization="user_owned", status="running"
        )
        db.add(row)
        item = DailyFeedItem(
            run_id=rid,
            video_id="old",
            snapshot={},
            category="face",
            link_status="sending",
            attachment_status="sending",
        )
        db.add(item)
        db.commit()
        jid = row.id
        iid = item.id
    worker = ContentWorker(factory)
    monkeypatch.setattr(worker, "links_loop", lambda: None)
    monkeypatch.setattr(worker, "feed_loop", lambda: None)
    monkeypatch.setattr(worker, "heartbeat_loop", lambda: None)
    worker.start()
    worker.close()
    with factory() as db:
        assert db.get(LinkImport, jid).status == "failed"
        assert db.get(DailyFeedRun, rid).status == "interrupted"
        assert db.get(DailyFeedRun, rid).summary_status == "unknown"
        assert db.get(DailyFeedItem, iid).link_status == "unknown"
        assert db.get(DailyFeedItem, iid).attachment_status == "unknown"


@pytest.mark.parametrize(
    "rectangles,expected",
    [([(20, 20, 30, 30)], "face"), ([(280, 120, 50, 50)], "unknown"), ([], "faceless")],
)
def test_face_groups_require_stable_edge_overlay(video, monkeypatch, rectangles, expected):
    import cv2

    monkeypatch.setattr(
        cv2,
        "CascadeClassifier",
        lambda _: SimpleNamespace(detectMultiScale=lambda *a, **kw: rectangles),
    )
    category, _ = sampled_faces([video, video, video])
    assert category == expected


def test_discovery_waits_for_publication_floor(monkeypatch):
    import asyncio
    from datetime import date

    monkeypatch.setattr(get_settings(), "daily_gameplay_not_before", date(2099, 1, 1))
    assert asyncio.run(daily_feed.discover_candidates()) == []


def test_discovery_filters_categories_and_ranks_unique_views(monkeypatch):
    import asyncio
    from datetime import date

    monkeypatch.setattr(get_settings(), "daily_gameplay_not_before", date(2020, 1, 1))

    def item(identifier, title, views, category="20"):
        return SimpleNamespace(
            external_id=identifier,
            title=title,
            view_count=views,
            published_at=datetime(2026, 11, 17, tzinfo=UTC),
            duration_seconds=60,
            raw_metadata={"live": "none", "category_id": category},
        )

    rows = [
        item("low", "GTA 6 gameplay mission", 100),
        item("high", "GTA VI gameplay walkthrough", 1000),
        item("promo", "GTA VI gameplay trailer", 99999),
        item("other", "GTA 6 gameplay", 99999, "24"),
    ]

    class Adapter:
        async def search(self, *args, **kwargs):
            assert kwargs["sort"] == "engagement"
            assert kwargs["published_after"].tzinfo is not None
            return rows

    monkeypatch.setattr(daily_feed, "YouTubeAdapter", Adapter)
    result = asyncio.run(daily_feed.discover_candidates())
    assert [row.external_id for row in result] == ["high", "low"]

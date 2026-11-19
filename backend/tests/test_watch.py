import asyncio
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from app.api.watch import WatchRequest, canonical_stream
from app.core.config import get_settings
from app.models import DiscoveredItem, DiscoverySchedule, ProcessingJob, WatchMoment
from app.services import live_sources, watch_worker
from app.services.live_sources import LiveError, YouTubeLive
from app.services.spikes import SpikeDetector


def payload(**kwargs):
    return {
        "source_url": "https://www.youtube.com/watch?v=Z0CPIt32Ux0",
        "creator_id": "UC_authorized",
        "creator_name": "Authorized creator",
        "authorization_notes": "Written permission received",
        "authorized": True,
        **kwargs,
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "https://youtube.com.evil.test/watch?v=Z0CPIt32Ux0",
        "https://user:password@youtube.com/watch?v=Z0CPIt32Ux0",
        "https://youtube.com:8443/watch?v=Z0CPIt32Ux0",
        "https://twitch.tv/a/videos",
        "https://youtu.be/invalid",
    ],
)
def test_reject_untrusted_stream_urls(url):
    with pytest.raises(ValueError):
        canonical_stream(url)


def test_canonical_stream_and_permission():
    assert (
        canonical_stream("https://youtu.be/Z0CPIt32Ux0?secret=discard")[1]
        == payload()["source_url"]
    )
    assert canonical_stream("https://twitch.tv/Creator")[1] == "https://www.twitch.tv/creator"
    with pytest.raises(ValidationError):
        WatchRequest(**payload(authorized=False))


def test_detector_baseline_spam_warmup_and_cooldown():
    detector = SpikeDetector()
    for bucket in range(30):
        detector.add(bucket * 10, "normal", "hello")
    for i in range(20):
        detector.add(300, str(i), "reaction")
    result = detector.advance(310)[0]
    assert result.spike and result.baseline == 1 and result.authors == 20
    for i in range(20):
        detector.add(310, str(i), "reaction")
    assert not detector.advance(320)[0].spike
    spam = SpikeDetector(warmup=0)
    for i in range(100):
        spam.add(0, "one-person", str(i))
    b = spam.advance(10)[0]
    assert b.count == 3 and not b.spike
    warm = SpikeDetector()
    for i in range(20):
        warm.add(0, str(i), "reaction")
    assert not warm.advance(10)[0].spike


def test_quiet_chat_and_out_of_order():
    d = SpikeDetector()
    assert all(not b.spike for b in d.advance(360))
    d.add(10, "late", "late")
    assert d.advance(370)[0].count == 0
    assert len(d.history) == 30


def test_watch_api_duplicate_stop_and_schedule(client):
    http, _ = client
    response = http.post("/api/v1/watch/sessions", json=payload())
    assert response.status_code == 201
    row = response.json()
    assert row["status"] == "queued"
    assert http.post("/api/v1/watch/sessions", json=payload()).status_code == 409
    assert http.post(f"/api/v1/watch/sessions/{row['id']}/stop").json()["status"] == "stopped"
    assert http.get(f"/api/v1/watch/sessions/{row['id']}/moments").json() == []
    assert http.post("/api/v1/watch/sessions", json=payload(authorized=False)).status_code == 422
    schedule = http.post(
        "/api/v1/discovery/schedules",
        json={
            "query": "gaming",
            "platforms": ["youtube"],
            "creator_ids": ["UC_authorized"],
            "interval_minutes": 60,
        },
    )
    assert schedule.status_code == 201
    sid = schedule.json()["id"]
    assert not http.patch(f"/api/v1/discovery/schedules/{sid}", json={"enabled": False}).json()[
        "enabled"
    ]
    assert http.get("/api/v1/watch/status").json()["youtube_configured"] is False


def test_watch_authentication(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(get_settings(), "app_access_token", SecretStr("private-server-token"))
    assert http.post("/api/v1/watch/sessions", json=payload()).status_code == 401
    assert http.get("/api/v1/watch/sessions").status_code == 401


def test_youtube_wait_live_creator_and_end(monkeypatch):
    monkeypatch.setattr(get_settings(), "youtube_api_key", SecretStr("test"))
    item = {"snippet": {"channelId": "UC_authorized"}, "liveStreamingDetails": {}}
    monkeypatch.setattr(live_sources, "request", lambda *a, **kw: {"items": [item]})
    source = YouTubeLive(SimpleNamespace(**payload()))
    assert not source.live()
    item["liveStreamingDetails"] = {"actualStartTime": "now", "activeLiveChatId": "chat"}
    assert source.live()
    item["snippet"]["channelId"] = "not-authorized"
    with pytest.raises(LiveError, match="owner"):
        source.live()
    item["snippet"]["channelId"] = "UC_authorized"
    item["liveStreamingDetails"]["actualEndTime"] = "ended"
    with pytest.raises(LiveError, match="ended"):
        source.live()


def test_youtube_poll_interval_and_historical_messages(monkeypatch):
    monkeypatch.setattr(get_settings(), "youtube_api_key", SecretStr("test"))
    source = YouTubeLive(SimpleNamespace(**payload()))
    result = {
        "nextPageToken": "next",
        "pollingIntervalMillis": 12000,
        "items": [
            {
                "snippet": {
                    "type": "textMessageEvent",
                    "publishedAt": "2026-11-16T10:00:00Z",
                    "displayMessage": "wow",
                },
                "authorDetails": {"channelId": "author"},
            }
        ],
    }
    calls = []

    def request(*a, **kw):
        calls.append(kw)
        return result

    monkeypatch.setattr(live_sources, "request", request)
    assert source.messages() == ([], 12)
    messages, delay = source.messages()
    assert messages[0][1:] == ("author", "wow") and delay == 12
    assert calls[1]["params"]["pageToken"] == "next"


def test_missing_credentials_and_storage_limits(client, monkeypatch):
    http, factory = client
    monkeypatch.setattr(watch_worker, "SessionLocal", factory)
    monkeypatch.setattr(watch_worker.shutil, "which", lambda _: "/fake/binary")
    row = http.post("/api/v1/watch/sessions", json=payload()).json()
    watch_worker.watch(row["id"])
    assert http.get("/api/v1/watch/sessions").json()[0]["status"] == "failed"
    assert "YOUTUBE_API_KEY" in http.get("/api/v1/watch/sessions").json()[0]["diagnostic"]
    monkeypatch.setattr(watch_worker.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    assert not watch_worker.space_ok()


def test_schedule_saves_only_allowlisted_creators(client, monkeypatch):
    http, factory = client
    monkeypatch.setattr(watch_worker, "SessionLocal", factory)
    row = http.post(
        "/api/v1/discovery/schedules",
        json={
            "query": "gaming",
            "platforms": ["youtube"],
            "creator_ids": ["UC_authorized"],
            "interval_minutes": 60,
        },
    ).json()

    async def fake_discover(db, request, mode):
        assert mode == "live"
        items = []
        for creator in ["UC_authorized", "someone_else"]:
            item = DiscoveredItem(
                platform="youtube",
                external_id=creator,
                title="video",
                canonical_url="https://youtube.com/",
                creator_id=creator,
                creator_name=creator,
                published_at=datetime.now(UTC),
            )
            db.add(item)
            items.append(item)
        db.commit()
        return SimpleNamespace(items=items, warnings=[])

    monkeypatch.setattr(watch_worker, "discover", fake_discover)
    asyncio.run(watch_worker.run_schedule(row["id"]))
    with factory() as db:
        saved = list(db.scalars(select(DiscoveredItem).where(DiscoveredItem.saved.is_(True))))
        assert len(saved) == 1 and saved[0].creator_id == "UC_authorized"
        schedule = db.get(DiscoverySchedule, row["id"])
        assert schedule.next_run_at > schedule.last_run_at


def test_real_segment_extract_import_and_render_queue(client, monkeypatch, tmp_path):
    http, factory = client
    monkeypatch.setattr(watch_worker, "SessionLocal", factory)
    row = http.post("/api/v1/watch/sessions", json=payload()).json()
    segment = tmp_path / "000000.ts"
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
            "3",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-f",
            "mpegts",
            str(segment),
        ],
        check=True,
    )
    (tmp_path / "segments.csv").write_text("000000.ts,0,3\n")
    segments = watch_worker.closed_segments(tmp_path)
    with factory() as db:
        moment = WatchMoment(
            watch_session_id=row["id"], start_seconds=0.5, end_seconds=2.5, reason="Test spike"
        )
        db.add(moment)
        db.commit()
        mid = moment.id
    watch_worker.materialize(row["id"], mid, tmp_path, segments)
    result = http.get(f"/api/v1/watch/sessions/{row['id']}/moments").json()[0]
    assert result["status"] == "ready" and result["processing_job_id"]
    media = http.get(f"/api/v1/media/{result['media_asset_id']}").json()
    assert media["authorization_status"] == "creator_authorized"
    assert media["source_provenance"]["source_url"] == payload()["source_url"]
    assert 1.8 < media["duration_seconds"] < 2.2
    with factory() as db:
        assert db.get(ProcessingJob, result["processing_job_id"]).status == "queued"
    from app.services.processing import Worker

    Worker(factory).run_job(result["processing_job_id"])
    job = http.get(f"/api/v1/processing/jobs/{result['processing_job_id']}").json()
    assert job["status"] == "completed"
    outputs = http.get(f"/api/v1/processing/jobs/{result['processing_job_id']}/outputs").json()
    assert len(outputs) == 2
    approved = http.post(
        f"/api/v1/media/{result['media_asset_id']}/review",
        json={"action": "approved", "notes": "Reviewed capture"},
    )
    assert approved.status_code == 200
    downloaded = http.get(f"/api/v1/outputs/{outputs[0]['id']}/download")
    assert downloaded.status_code == 200 and len(downloaded.content) > 1000


def test_twitch_authenticated_tls_chat_and_ping(monkeypatch):
    from app.services.live_sources import TwitchLive

    s = get_settings()
    monkeypatch.setattr(s, "twitch_user_token", SecretStr("test-token"))
    monkeypatch.setattr(s, "twitch_chat_login", "testuser")
    monkeypatch.setattr(s, "twitch_client_id", "client")
    sent = []

    class Socket:
        def settimeout(self, value):
            pass

        def sendall(self, value):
            sent.append(value)

        def recv(self, size):
            return b"PING :tmi.twitch.tv\r\n@user-id=123;tmi-sent-ts=1794823200000 :u!u PRIVMSG #creator :wow\r\n"

        def close(self):
            pass

    monkeypatch.setattr(live_sources.socket, "create_connection", lambda *a, **kw: Socket())
    monkeypatch.setattr(
        live_sources.ssl,
        "create_default_context",
        lambda: SimpleNamespace(wrap_socket=lambda raw, **kw: raw),
    )
    source = TwitchLive(
        SimpleNamespace(source_url="https://www.twitch.tv/creator", creator_id="123")
    )
    messages, _ = source.messages()
    assert messages[0][1:] == ("123", "wow")
    assert b"PASS oauth:test-token" in sent[0]
    assert sent[1].startswith(b"PONG")
    source.close()


def test_watch_retries_are_bounded(client, monkeypatch):
    http, factory = client
    monkeypatch.setattr(watch_worker, "SessionLocal", factory)
    monkeypatch.setattr(watch_worker.shutil, "which", lambda _: "/fake/binary")
    monkeypatch.setattr(watch_worker, "pause", lambda *a: None)
    calls = []

    class Offline:
        def __init__(self, row):
            pass

        def live(self):
            calls.append(1)
            raise LiveError("temporary")

        def close(self):
            pass

    monkeypatch.setattr(watch_worker, "YouTubeLive", Offline)
    row = http.post("/api/v1/watch/sessions", json=payload()).json()
    watch_worker.watch(row["id"])
    assert len(calls) == 6
    result = http.get("/api/v1/watch/sessions").json()[0]
    assert result["status"] == "failed" and "Reconnect limit" in result["diagnostic"]


def test_gap_is_not_silently_joined(client, monkeypatch, tmp_path):
    http, factory = client
    monkeypatch.setattr(watch_worker, "SessionLocal", factory)
    row = http.post("/api/v1/watch/sessions", json=payload()).json()
    with factory() as db:
        moment = WatchMoment(
            watch_session_id=row["id"], start_seconds=0, end_seconds=10, reason="spike"
        )
        db.add(moment)
        db.commit()
        mid = moment.id
    watch_worker.materialize(
        row["id"], mid, tmp_path, [(tmp_path / "a.ts", 0, 3), (tmp_path / "b.ts", 5, 10)]
    )
    result = http.get(f"/api/v1/watch/sessions/{row['id']}/moments").json()[0]
    assert result["status"] == "missed_buffer" and result["media_asset_id"] is None


def test_supervisor_restart_recovery_and_single_owner(tmp_path):
    import os
    import sys
    import time
    from pathlib import Path

    from sqlalchemy.orm import sessionmaker

    from app.db.session import build_engine
    from app.models import Base, WatchSession

    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path}/worker.db"
    engine = build_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        row = WatchSession(
            platform="youtube",
            source_url=payload()["source_url"],
            creator_id="UC_authorized",
            creator_name="Creator",
            authorization_notes="Written permission",
            options=WatchRequest(**payload()).model_dump(),
            status="recording",
        )
        db.add(row)
        db.flush()
        db.add(
            WatchMoment(
                watch_session_id=row.id, start_seconds=0, end_seconds=20, reason="Interrupted spike"
            )
        )
        db.commit()
        sid = row.id
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "STORAGE_ROOT": str(tmp_path / "storage"),
        "APP_ENV": "test",
        "APP_ACCESS_TOKEN": "",
        "STREAMLINK_BINARY": "intentionally-missing-capture-tool",
        "YOUTUBE_API_KEY": "",
        "TWITCH_USER_TOKEN": "",
        "WHISPER_MODEL_PATH": "",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.services.watch_worker"],
        cwd=backend,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with factory() as db:
                if db.get(WatchSession, sid).status == "failed":
                    break
            time.sleep(0.1)
        with factory() as db:
            assert db.get(WatchSession, sid).status == "failed"
            assert db.scalar(select(WatchMoment)).status == "incomplete"
        duplicate = subprocess.run(
            [sys.executable, "-m", "app.services.watch_worker"],
            cwd=backend,
            env=env,
            capture_output=True,
            timeout=5,
        )
        assert duplicate.returncode != 0 and b"already running" in duplicate.stderr
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        engine.dispose()
    assert proc.returncode == 0

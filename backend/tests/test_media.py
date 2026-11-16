import hashlib
import subprocess

import pytest

from app.models import MediaAsset, ProcessingJob
from app.services.media import storage_path
from app.services.processing import Worker


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("video") / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        timeout=20,
    )
    return path


def upload(c, video, authorization="user_owned"):
    with video.open("rb") as f:
        response = c.post(
            "/api/v1/media/upload",
            files={"file": ("../../test.mp4", f, "video/mp4")},
            data={
                "authorization_status": authorization,
                "authorization_notes": "Generated test fixture",
            },
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_validation_dedup_and_paths(client, video):
    c, factory = client
    assert (
        c.post(
            "/api/v1/media/upload",
            files={"file": ("bad.txt", b"bad", "text/plain")},
            data={"authorization_status": "user_owned"},
        ).status_code
        == 415
    )
    assert (
        c.post(
            "/api/v1/media/upload",
            files={"file": ("bad.mp4", b"bad", "video/mp4")},
            data={"authorization_status": "user_owned"},
        ).status_code
        == 422
    )
    a = upload(c, video)
    b = upload(c, video)
    assert a["id"] == b["id"]
    assert a["original_filename"] == "test.mp4"
    assert a["sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert "storage_path" not in a
    assert a["width"] == 320 and a["audio_codec"] == "aac"
    with factory() as db:
        asset = db.get(MediaAsset, a["id"])
        assert ".." not in asset.stored_filename
    assert c.get(f"/api/v1/media/{a['id']}/download").content == video.read_bytes()
    with pytest.raises(Exception):
        storage_path("../../private")


def test_upload_size_and_authorization(client, video, monkeypatch):
    from app import main

    c, _ = client
    monkeypatch.setattr(main.settings, "max_upload_mb", 1)
    r = c.post(
        "/api/v1/media/upload",
        files={"file": ("large.mp4", b"0" * 1100000, "video/mp4")},
        data={"authorization_status": "user_owned"},
    )
    assert r.status_code == 413
    asset = upload(c, video, "unverified")
    assert c.post("/api/v1/processing/jobs", json={"media_id": asset["id"]}).status_code == 403


def test_real_video_pipeline_review_download_and_subtitles(client, video):
    c, factory = client
    asset = upload(c, video)
    srt = "1\n00:00:00,000 --> 00:00:01,500\nTest captions\n"
    assert c.patch(f"/api/v1/media/{asset['id']}", json={"subtitle_srt": srt}).status_code == 200
    response = c.post(
        "/api/v1/processing/jobs",
        json={
            "media_id": asset["id"],
            "profiles": ["original", "shorts_1080x1920"],
            "trim_start_seconds": 0.25,
            "trim_end_seconds": 1.25,
            "normalize_audio": True,
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()
    worker = Worker(factory)
    worker.run_job(job["id"])
    status = c.get(f"/api/v1/processing/jobs/{job['id']}").json()
    assert status["status"] == "completed", status
    outputs = c.get(f"/api/v1/processing/jobs/{job['id']}/outputs").json()
    assert len(outputs) == 2
    assert {(o["width"], o["height"]) for o in outputs} == {(320, 180), (1080, 1920)}
    assert all(o["video_codec"] == "h264" and o["audio_codec"] == "aac" for o in outputs)
    assert c.get(f"/api/v1/outputs/{outputs[0]['id']}/download").status_code == 409
    assert (
        c.post(
            f"/api/v1/media/{asset['id']}/review",
            json={"action": "approved", "notes": "Checked both profiles"},
        ).status_code
        == 200
    )
    for output in outputs:
        result = c.get(f"/api/v1/outputs/{output['id']}/download")
        assert result.status_code == 200
        assert hashlib.sha256(result.content).hexdigest() == output["sha256"]
        assert (
            "00:00:00,000 --> 00:00:01,000"
            in c.get(f"/api/v1/outputs/{output['id']}/subtitles").text
        )
    assert c.post(f"/api/v1/outputs/{outputs[0]['id']}/telegram-send", json={}).status_code == 409
    assert len(c.get(f"/api/v1/processing/jobs/{job['id']}/events").json()) == 3


def test_retry_cancel_restart(client, video, monkeypatch):
    c, factory = client
    asset = upload(c, video)
    job = c.post(
        "/api/v1/processing/jobs", json={"media_id": asset["id"], "profiles": ["original"]}
    ).json()
    worker = Worker(factory)
    original = worker.run_command

    def timeout(*args):
        raise TimeoutError()

    monkeypatch.setattr(worker, "run_command", timeout)
    worker.run_job(job["id"])
    failed = c.get(f"/api/v1/processing/jobs/{job['id']}").json()
    assert failed["status"] == "failed" and failed["retryable"]
    assert c.post(f"/api/v1/processing/jobs/{job['id']}/retry").status_code == 200
    monkeypatch.setattr(worker, "run_command", original)
    worker.run_job(job["id"])
    assert c.get(f"/api/v1/processing/jobs/{job['id']}").json()["attempt_count"] == 2
    second = c.post(
        "/api/v1/processing/jobs", json={"media_id": asset["id"], "profiles": ["original"]}
    ).json()
    assert c.post(f"/api/v1/processing/jobs/{second['id']}/cancel").json()["status"] == "cancelled"
    third = c.post(
        "/api/v1/processing/jobs", json={"media_id": asset["id"], "profiles": ["original"]}
    ).json()
    with factory() as db:
        j = db.get(ProcessingJob, third["id"])
        j.status = "running"
        j.attempt_count = 1
        db.commit()
    worker.recover()
    assert c.get(f"/api/v1/processing/jobs/{third['id']}").json()["status"] == "queued"
    worker.run_job(third["id"])
    assert c.get(f"/api/v1/processing/jobs/{third['id']}").json()["status"] == "completed"


def test_invalid_trim_and_captions(client, video):
    c, _ = client
    asset = upload(c, video)
    assert (
        c.post(
            "/api/v1/processing/jobs", json={"media_id": asset["id"], "trim_end_seconds": 20}
        ).status_code
        == 422
    )
    assert c.patch(f"/api/v1/media/{asset['id']}", json={"subtitle_srt": "bad"}).status_code == 422
    assert (
        c.post(
            "/api/v1/processing/jobs", json={"media_id": asset["id"], "burn_subtitles": True}
        ).status_code
        == 422
    )
    assert c.post("/api/v1/ai/suggest", json={"context": "test clip"}).status_code == 409
    assert c.post(f"/api/v1/media/{asset['id']}/transcribe").status_code == 409


def test_delete_confirmation_and_archive(client, video):
    c, _ = client
    asset = upload(c, video)
    assert c.request("DELETE", f"/api/v1/media/{asset['id']}", json={}).status_code == 400
    assert c.patch(f"/api/v1/media/{asset['id']}", json={"archived": True}).status_code == 200
    assert c.get("/api/v1/media").json() == []
    assert len(c.get("/api/v1/media?archived=true").json()) == 1


def test_token_auth_and_origin_guard(client, monkeypatch):
    from pydantic import SecretStr

    from app import main

    c, _ = client
    monkeypatch.setattr(
        main.settings, "app_access_token", SecretStr("test-token-that-is-not-disclosed")
    )
    assert c.get("/api/v1/media").status_code == 401
    assert c.post("/api/v1/auth/login", json={"token": "wrong"}).status_code == 401
    assert (
        c.post("/api/v1/auth/login", json={"token": "test-token-that-is-not-disclosed"}).status_code
        == 200
    )
    assert c.get("/api/v1/media").status_code == 200
    assert "test-token" not in c.get("/api/v1/system/status").text
    assert (
        c.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    )
    assert c.post("/api/v1/auth/logout").status_code == 200
    assert c.get("/api/v1/media").status_code == 401


def test_portrait_silent_and_anamorphic_sources(client, tmp_path):
    c, factory = client
    source = tmp_path / "portrait.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=180x320:rate=24",
            "-t",
            "0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    asset = upload(c, source)
    assert asset["audio_codec"] is None
    job = c.post(
        "/api/v1/processing/jobs",
        json={
            "media_id": asset["id"],
            "profiles": ["shorts_720x1280"],
            "fps": 24,
            "mute_audio": True,
        },
    ).json()
    Worker(factory).run_job(job["id"])
    assert c.get(f"/api/v1/processing/jobs/{job['id']}").json()["status"] == "completed"
    result = c.get(f"/api/v1/processing/jobs/{job['id']}/outputs").json()[0]
    assert result["width"] == 720 and result["height"] == 1280 and result["audio_codec"] is None
    source = tmp_path / "anamorphic.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24",
            "-t",
            "0.5",
            "-vf",
            "setsar=2/1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    asset = upload(c, source)
    assert asset["width"] == 640
    job = c.post(
        "/api/v1/processing/jobs",
        json={"media_id": asset["id"], "profiles": ["original"], "fps": 24},
    ).json()
    Worker(factory).run_job(job["id"])
    result = c.get(f"/api/v1/processing/jobs/{job['id']}/outputs").json()[0]
    assert (result["width"], result["height"]) == (640, 180)


def test_non_ascii_login_is_a_normal_authentication_failure(client, monkeypatch):
    from pydantic import SecretStr

    from app import main

    c, _ = client
    monkeypatch.setattr(main.settings, "app_access_token", SecretStr("correct-token"))
    assert c.post("/api/v1/auth/login", json={"token": "🔑"}).status_code == 401

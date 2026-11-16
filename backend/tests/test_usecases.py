"""Use-case acceptance against a real migrated database, HTTP server and worker process."""

import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def test_discover_import_render_review_download_and_restart(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        DATABASE_URL=f"sqlite:///{tmp_path}/acceptance.db",
        STORAGE_ROOT=str(tmp_path / "storage"),
        PLATFORM_MODE="mock",
        APP_ENV="test",
        WORKER_ENABLED="true",
        APP_ACCESS_TOKEN="isolated-functional-test-access-token",
        API_V1_PREFIX="/api/v1",
    )
    for key in [
        "OPENAI_API_KEY",
        "AI_MODEL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "YOUTUBE_API_KEY",
        "REDDIT_CLIENT_SECRET",
        "TWITCH_CLIENT_SECRET",
        "X_BEARER_TOKEN",
    ]:
        env[key] = ""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=env,
        capture_output=True,
        check=True,
        timeout=30,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (tmp_path / "server.log").open("w")
    process = None

    def start():
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=backend,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise AssertionError("Server exited before readiness")
                try:
                    if (
                        httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=1).status_code
                        == 200
                    ):
                        return child
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            raise AssertionError("Server readiness timed out")
        except Exception:
            child.terminate()
            child.wait(timeout=10)
            raise

    def stop(child):
        child.terminate()
        try:
            child.wait(timeout=45)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
            raise

    try:
        process = start()
        fixture = tmp_path / "fixture.mp4"
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
                "sine=frequency=440",
                "-t",
                "1.5",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(fixture),
            ],
            check=True,
            timeout=20,
        )
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
            assert client.get("/").status_code == 200
            assert client.get("/api/v1/media").status_code == 401
            login = client.post("/api/v1/auth/login", json={"token": env["APP_ACCESS_TOKEN"]})
            assert login.status_code == 200
            assert "httponly" in login.headers["set-cookie"].lower()
            search_body = {
                "query": "Isolated GTA VI test",
                "platforms": ["youtube", "reddit", "twitch", "tiktok", "x", "instagram"],
                "limit": 1,
            }
            search = client.post("/api/v1/discovery/search", json=search_body)
            search.raise_for_status()
            assert search.json()["result_count"] == 6
            client.post("/api/v1/discovery/search", json=search_body).raise_for_status()
            assert client.get("/api/v1/stats/overview").json()["discovered_items"] == 6
            item_id = search.json()["items"][0]["id"]
            client.post(f"/api/v1/discovery/items/{item_id}/save").raise_for_status()
            assert len(client.get("/api/v1/clips").json()) == 1
            with fixture.open("rb") as handle:
                imported = client.post(
                    "/api/v1/media/upload",
                    files={"file": ("fixture.mp4", handle, "video/mp4")},
                    data={"authorization_status": "user_owned", "discovered_item_id": item_id},
                )
            imported.raise_for_status()
            media_id = imported.json()["id"]
            client.patch(
                f"/api/v1/media/{media_id}",
                json={"subtitle_srt": "1\n00:00:00,000 --> 00:00:01,500\nAcceptance caption\n"},
            ).raise_for_status()
            queued = client.post(
                "/api/v1/processing/jobs",
                json={
                    "media_id": media_id,
                    "profiles": ["original", "shorts_1080x1920"],
                    "trim_start_seconds": 0.25,
                    "trim_end_seconds": 1.25,
                },
            )
            queued.raise_for_status()
            job_id = queued.json()["id"]
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/processing/jobs/{job_id}").json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.1)
            assert job["status"] == "completed", job
            outputs = client.get(f"/api/v1/processing/jobs/{job_id}/outputs").json()
            assert len(outputs) == 2
            assert {(o["width"], o["height"]) for o in outputs} == {(320, 180), (1080, 1920)}
            output_id = outputs[0]["id"]
            assert client.get(f"/api/v1/outputs/{output_id}/download").status_code == 409
            client.post(
                f"/api/v1/media/{media_id}/review", json={"action": "rejected"}
            ).raise_for_status()
            assert client.get(f"/api/v1/outputs/{output_id}/download").status_code == 409
            client.post(
                f"/api/v1/media/{media_id}/review", json={"action": "approved"}
            ).raise_for_status()
            for output in outputs:
                result = client.get(f"/api/v1/outputs/{output['id']}/download")
                result.raise_for_status()
                assert hashlib.sha256(result.content).hexdigest() == output["sha256"]
                assert output["video_codec"] == "h264" and output["audio_codec"] == "aac"
                assert abs(output["duration_seconds"] - 1) < 0.1
            ranged = client.get(
                f"/api/v1/outputs/{output_id}/download?preview=true",
                headers={"Range": "bytes=0-99"},
            )
            assert ranged.status_code == 206 and len(ranged.content) == 100
            assert (
                "00:00:00,000 --> 00:00:01,000"
                in client.get(f"/api/v1/outputs/{output_id}/subtitles").text
            )
            client.patch(
                f"/api/v1/media/{media_id}",
                json={"publishing_metadata": {"title": "Revised title"}},
            ).raise_for_status()
            assert client.get(f"/api/v1/outputs/{output_id}/download").status_code == 409
            client.post(
                f"/api/v1/media/{media_id}/review", json={"action": "approved"}
            ).raise_for_status()
            assert (
                client.post(f"/api/v1/outputs/{output_id}/telegram-send", json={}).status_code
                == 409
            )
            assert (
                client.post("/api/v1/ai/suggest", json={"context": "synthetic fixture"}).status_code
                == 409
            )
            stop(process)
            process = None
            process = start()
            assert client.get(f"/api/v1/processing/jobs/{job_id}").json()["status"] == "completed"
            assert client.get(f"/api/v1/outputs/{output_id}/download").status_code == 200
            assert client.get("/api/v1/system/status").json()["worker"] == "running"
            assert len(client.get(f"/api/v1/media/{media_id}/reviews").json()) == 3
            assert client.post("/api/v1/auth/logout").status_code == 200
            assert client.get(f"/api/v1/outputs/{output_id}/download").status_code == 401
        # Safe logs must not contain authentication tokens or local user-supplied secrets.
        log.flush()
        assert env["APP_ACCESS_TOKEN"] not in (tmp_path / "server.log").read_text()
    finally:
        if process is not None:
            stop(process)
        log.close()

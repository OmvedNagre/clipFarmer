import json

import httpx
import pytest
from pydantic import SecretStr

from app.api import delivery
from app.core.config import get_settings
from app.models import MediaAsset, ProcessingJob, VideoOutput
from app.services.assistance import OpenAIProvider


@pytest.fixture
def ready_output(client, tmp_path):
    c, factory = client
    from app.services.media import storage_path

    path = storage_path("outputs/telegram-test.mp4")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test")
    with factory() as db:
        asset = MediaAsset(
            original_filename="test.mp4",
            stored_filename="test.mp4",
            storage_path="originals/test.mp4",
            mime_type="video/mp4",
            size_bytes=4,
            sha256="a" * 64,
            duration_seconds=1,
            width=2,
            height=2,
            video_codec="h264",
            audio_codec=None,
            authorization_status="user_owned",
            review_status="approved",
            publishing_metadata={"title": "Test title"},
        )
        db.add(asset)
        db.flush()
        job = ProcessingJob(media_asset_id=asset.id, status="completed", options={})
        db.add(job)
        db.flush()
        output = VideoOutput(
            processing_job_id=job.id,
            profile="original",
            storage_path="outputs/telegram-test.mp4",
            filename="test.mp4",
            size_bytes=4,
            sha256="b" * 64,
            duration_seconds=1,
            width=2,
            height=2,
            video_codec="h264",
            audio_codec=None,
        )
        db.add(output)
        db.commit()
        identity = output.id
    return c, identity


class FakeClient:
    result = {"ok": True, "result": {"message_id": 42}}
    failed = False

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, *args, **kwargs):
        if self.failed:
            raise httpx.ReadTimeout("SECRET_URL")
        return httpx.Response(
            200, json=self.result, request=httpx.Request("POST", "https://example.com")
        )

    async def get(self, *args, **kwargs):
        return await self.post(*args, **kwargs)


@pytest.fixture
def fake_telegram(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "telegram_chat_id", "test-chat")
    monkeypatch.setattr(delivery.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(FakeClient, "failed", False)
    monkeypatch.setattr(FakeClient, "result", {"ok": True, "result": {"message_id": 42}})


def test_telegram_success_and_duplicate_protection(ready_output, fake_telegram):
    c, identity = ready_output
    assert c.post("/api/v1/telegram/test").json()["status"] == "connected"
    first = c.post(f"/api/v1/outputs/{identity}/telegram-send", json={})
    assert first.json()["status"] == "sent"
    assert c.post(f"/api/v1/outputs/{identity}/telegram-send", json={}).status_code == 409
    assert (
        c.post(f"/api/v1/outputs/{identity}/telegram-send", json={"confirm_resend": True}).json()[
            "status"
        ]
        == "sent"
    )
    assert "test-secret" not in c.get(f"/api/v1/outputs/{identity}/deliveries").text


def test_telegram_timeout_is_uncertain_not_retried(ready_output, fake_telegram, monkeypatch):
    c, identity = ready_output
    monkeypatch.setattr(FakeClient, "failed", True)
    result = c.post(f"/api/v1/outputs/{identity}/telegram-send", json={})
    assert result.json()["status"] == "unknown"
    assert "SECRET_URL" not in result.text
    assert c.post(f"/api/v1/outputs/{identity}/telegram-send", json={}).status_code == 409


@pytest.mark.asyncio
async def test_ai_metadata_contract(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("private"))
    monkeypatch.setattr(settings, "ai_model", "test-model")
    draft = {
        "title": "A test",
        "description": "Generated fixture",
        "hashtags": "#test",
        "hook": "Watch",
    }
    monkeypatch.setattr(FakeClient, "failed", False)
    monkeypatch.setattr(
        FakeClient,
        "result",
        {"output": [{"content": [{"type": "output_text", "text": json.dumps(draft)}]}]},
    )
    from app.services import assistance

    monkeypatch.setattr(assistance.httpx, "AsyncClient", FakeClient)
    assert await OpenAIProvider().suggest("context") == draft

import pytest
from pydantic import SecretStr

from app.adapters import live
from app.adapters.live import ConnectorError, RedditAdapter, TwitchAdapter, XAdapter, YouTubeAdapter
from app.core.config import get_settings


@pytest.fixture
def credentials(monkeypatch):
    settings = get_settings()
    for key in [
        "youtube_api_key",
        "reddit_client_secret",
        "twitch_client_secret",
        "x_bearer_token",
    ]:
        monkeypatch.setattr(settings, key, SecretStr("test-secret"))
    monkeypatch.setattr(settings, "reddit_client_id", "test-client")
    monkeypatch.setattr(settings, "twitch_client_id", "test-client")


@pytest.mark.asyncio
async def test_youtube_contract(credentials, monkeypatch):
    calls = []

    async def request(method, url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/search"):
            return {
                "items": [
                    {
                        "id": {"videoId": "abc"},
                        "snippet": {
                            "title": "GTA &amp; VI",
                            "channelTitle": "Creator",
                            "publishedAt": "2026-01-01T00:00:00Z",
                        },
                    }
                ]
            }
        return {
            "items": [
                {
                    "id": "abc",
                    "contentDetails": {"duration": "PT1M2S"},
                    "statistics": {"viewCount": "42"},
                }
            ]
        }

    monkeypatch.setattr(live, "request_json", request)
    rows = await YouTubeAdapter().search("GTA VI", 2)
    assert (
        rows[0].duration_seconds == 62 and rows[0].view_count == 42 and rows[0].title == "GTA & VI"
    )
    assert "test-secret" not in rows[0].model_dump_json()
    assert calls[0][1]["params"]["type"] == "video"


@pytest.mark.asyncio
async def test_reddit_contract(credentials, monkeypatch):
    async def request(method, url, **kwargs):
        if url.endswith("access_token"):
            return {"access_token": "private"}
        assert kwargs["headers"]["Authorization"] == "Bearer private"
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "post",
                            "title": "GTA VI",
                            "permalink": "/r/test/comments/post",
                            "author": "creator",
                            "created_utc": 1700000000,
                            "score": 9,
                            "num_comments": 4,
                        }
                    }
                ]
            }
        }

    monkeypatch.setattr(live, "request_json", request)
    rows = await RedditAdapter().search("GTA VI")
    assert rows[0].comment_count == 4 and rows[0].raw_metadata["score"] == 9
    assert rows[0].view_count is None


@pytest.mark.asyncio
async def test_twitch_category_scope(credentials, monkeypatch):
    async def request(method, url, **kwargs):
        if url.endswith("/token"):
            return {"access_token": "private"}
        if url.endswith("/categories"):
            return {"data": [{"id": "gta", "name": "Grand Theft Auto VI"}]}
        assert kwargs["params"]["game_id"] == "gta"
        return {
            "data": [
                {
                    "id": "clip",
                    "title": "Clip",
                    "url": "https://clips.twitch.tv/clip",
                    "created_at": "2026-01-01T00:00:00Z",
                    "duration": 12,
                    "view_count": 7,
                }
            ]
        }

    monkeypatch.setattr(live, "request_json", request)
    rows = await TwitchAdapter().search("Grand Theft Auto VI")
    assert rows[0].raw_metadata["search_scope"] == "category_clips"


@pytest.mark.asyncio
async def test_x_contract(credentials, monkeypatch):
    async def request(method, url, **kwargs):
        assert kwargs["params"]["max_results"] == 10
        return {
            "data": [
                {
                    "id": "123",
                    "text": "GTA VI",
                    "created_at": "2026-01-01T00:00:00Z",
                    "author_id": "u",
                    "public_metrics": {"like_count": 8},
                }
            ],
            "includes": {"users": [{"id": "u", "username": "creator"}]},
        }

    monkeypatch.setattr(live, "request_json", request)
    rows = await XAdapter().search("GTA VI", 1)
    assert rows[0].creator_name == "creator" and rows[0].like_count == 8


@pytest.mark.asyncio
async def test_quota_safe_error(monkeypatch):
    import httpx

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            return httpx.Response(429, json={"secret": "do not echo"})

    monkeypatch.setattr(live.httpx, "AsyncClient", Client)
    with pytest.raises(ConnectorError) as exc:
        await live.request_json("GET", "https://example.com")
    assert exc.value.status == "rate_limited" and "secret" not in str(exc.value)


def test_source_submission(client):
    c, _ = client
    source = {
        "url": "https://www.instagram.com/p/demo/?tracking=value",
        "title": "Creator submission",
    }
    a = c.post("/api/v1/discovery/submit", json=source)
    assert a.status_code == 200, a.text
    assert a.json()["canonical_url"] == "https://www.instagram.com/p/demo/"
    assert a.json()["raw_metadata"]["user_submitted"]
    assert c.post("/api/v1/discovery/submit", json=source).json()["id"] == a.json()["id"]
    assert (
        c.post(
            "/api/v1/discovery/submit", json={"url": "http://127.0.0.1/private", "title": "bad"}
        ).status_code
        == 422
    )

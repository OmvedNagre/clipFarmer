import json

import pytest
from sqlalchemy import func, select

from app import main
from app.adapters.registry import PLATFORMS, get_adapter
from app.models import DiscoveredItem


def search(client, **changes):
    body = {"query": "GTA VI", "platforms": list(PLATFORMS), "limit": 2}
    body.update(changes)
    return client.post("/api/v1/discovery/search", json=body)


def test_health_and_system(client):
    c, _ = client
    assert c.get("/api/v1/health").json()["status"] == "healthy"
    data = c.get("/api/v1/system/status").json()
    assert data["database"] == "connected"
    assert data["storage"] == "available"
    assert data["worker"] == "stopped"
    assert len(data["connectors"]) == 6


@pytest.mark.asyncio
async def test_six_normalized_deterministic_adapters():
    for platform in PLATFORMS:
        adapter = get_adapter(platform)
        first = await adapter.search("GTA VI", 2)
        assert first == await adapter.search("GTA VI", 2)
        assert all(i.raw_metadata["demo"] and i.platform == platform for i in first)
        assert (await adapter.health_check())["status"] == "connected"


def test_discovery_dedup_and_history(client):
    c, factory = client
    first, second = search(c).json(), search(c).json()
    assert first["result_count"] == second["result_count"] == 12
    assert {i["id"] for i in first["items"]} == {i["id"] for i in second["items"]}
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(DiscoveredItem)) == 12
    for result in [first, second]:
        assert len(c.get("/api/v1/discovery/searches/" + result["search_id"]).json()["items"]) == 12
    assert len(c.get("/api/v1/discovery/searches").json()) == 2


def test_one_adapter_failure_preserves_other_results(client, monkeypatch):
    c, _ = client
    from app.services import discovery

    class Failed:
        async def search(self, *args):
            raise RuntimeError("SECRET_TOKEN=do-not-leak")

    monkeypatch.setattr(
        discovery, "get_adapter", lambda p, m: Failed() if p == "reddit" else get_adapter(p, m)
    )
    result = search(c).json()
    assert result["result_count"] == 10
    assert "reddit" in result["errors"]
    assert "SECRET_TOKEN" not in json.dumps(result)


def test_save_filters_stats_and_new_connection_persistence(client):
    c, factory = client
    item = search(c).json()["items"][0]
    assert c.post(f"/api/v1/discovery/items/{item['id']}/save").json()["saved"] is True
    assert c.post(f"/api/v1/discovery/items/{item['id']}/save").status_code == 200
    assert len(c.get("/api/v1/clips").json()) == 1
    assert c.get("/api/v1/clips?q=no-match").json() == []
    assert c.get("/api/v1/stats/overview").json()["saved_items"] == 1
    assert c.get("/api/v1/stats/overview").json()["discovered_items"] == 12
    with factory() as db:
        assert db.get(DiscoveredItem, item["id"]).saved is True
    assert sum(p["count"] for p in c.get("/api/v1/stats/platforms").json()) == 12


def test_connector_disable_test_and_live_status(client, monkeypatch):
    c, _ = client
    assert (
        c.patch("/api/v1/sources/youtube", json={"enabled": False}).json()["status"] == "disabled"
    )
    result = search(c, platforms=["youtube", "reddit"]).json()
    assert result["result_count"] == 2
    assert "youtube" in result["errors"]
    assert c.post("/api/v1/sources/reddit/test").json()["last_checked_at"]
    monkeypatch.setattr(main.settings, "platform_mode", "live")
    sources = c.get("/api/v1/sources").json()
    assert not any(s["status"] == "connected" for s in sources)
    assert not any(s["capabilities"] for s in sources)
    assert search(c, platforms=["reddit"]).json()["result_count"] == 0


@pytest.mark.parametrize(
    "payload",
    [{"query": " "}, {"limit": 51}, {"platforms": []}, {"platforms": ["invalid"]}, {"sort": "bad"}],
)
def test_validates_search_without_echoing_inputs(client, payload):
    c, _ = client
    result = search(c, **payload)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "invalid_input"
    assert result.json()["error"]["request_id"]


def test_not_found_and_rate_limit(client):
    c, _ = client
    assert c.get("/api/v1/clips/missing").status_code == 404
    for _ in range(30):
        assert search(c, platforms=["youtube"], limit=1).status_code == 200
    limited = search(c)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"


def test_config_rejects_invalid_mode():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(platform_mode="pretend")


def test_expanding_search_handles_existing_and_new_utc_records(client):
    c, _ = client
    assert search(c, limit=1).status_code == 200
    result = search(c, limit=3)
    assert result.status_code == 200
    assert result.json()["result_count"] == 18
    assert all(i["published_at"].endswith("Z") for i in result.json()["items"])

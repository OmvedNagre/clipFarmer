import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

from app import main
from app.db.session import build_engine
from app.models import Base


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main.settings, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(main.settings, "platform_mode", "mock")
    monkeypatch.setattr(main.settings, "worker_enabled", False)
    for name in [
        "app_access_token",
        "openai_api_key",
        "telegram_bot_token",
        "youtube_api_key",
        "reddit_client_secret",
        "twitch_client_secret",
        "twitch_user_token",
        "x_bearer_token",
    ]:
        monkeypatch.setattr(main.settings, name, SecretStr(""))
    monkeypatch.setattr(main.settings, "telegram_chat_id", "")
    monkeypatch.setattr(main.settings, "ai_model", "")
    main.requests_by_host.clear()

    def db():
        with factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = db
    with TestClient(main.app) as client:
        yield client, factory
    main.app.dependency_overrides.clear()
    engine.dispose()

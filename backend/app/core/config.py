from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "VI ClipForge"
    api_v1_prefix: str = Field(default="/api/v1", pattern=r"^/api/v[0-9]+$")
    database_url: str = "sqlite:///./vi_clipforge.db"
    storage_root: Path = Path("../storage")
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"
    )
    max_upload_mb: int = Field(default=500, gt=0, le=10000)
    platform_mode: Literal["mock", "live"] = "mock"

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    processing_timeout_seconds: int = Field(default=3600, ge=5, le=86400)
    worker_enabled: bool = True
    app_access_token: SecretStr = SecretStr("")
    youtube_api_key: SecretStr = SecretStr("")
    reddit_client_id: str = ""
    reddit_client_secret: SecretStr = SecretStr("")
    reddit_user_agent: str = "VIClipForge/1.0 (local research workspace)"
    twitch_client_id: str = ""
    twitch_client_secret: SecretStr = SecretStr("")
    x_bearer_token: SecretStr = SecretStr("")
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    telegram_max_upload_mb: int = Field(default=49, ge=1, le=49)
    openai_api_key: SecretStr = SecretStr("")
    ai_model: str = ""
    transcription_model: str = "whisper-1"

    @model_validator(mode="after")
    def secure_production(self):
        if self.app_env == "production" and len(self.app_access_token.get_secret_value()) < 32:
            raise ValueError("Production requires APP_ACCESS_TOKEN with at least 32 characters")
        return self

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

Platform = Literal["youtube", "reddit", "twitch", "tiktok", "x", "instagram"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    platforms: list[Platform] = Field(min_length=1, max_length=6)
    limit: int = Field(default=12, ge=1, le=50)
    sort: Literal["newest", "engagement"] = "newest"

    @field_validator("query")
    @classmethod
    def validate_query(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Enter a search query")
        return value

    @field_validator("platforms")
    @classmethod
    def unique_platforms(cls, value):
        return list(dict.fromkeys(value))


class DiscoveredItemCreate(BaseModel):
    platform: Platform
    external_id: str
    title: str
    description: str = ""
    canonical_url: HttpUrl
    thumbnail_url: str | None = None
    creator_id: str | None = None
    creator_name: str
    published_at: datetime
    duration_seconds: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    media_access_type: str = "metadata_only"
    raw_metadata: dict = Field(default_factory=dict)


class ItemResponse(DiscoveredItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    saved: bool
    created_at: datetime


class SourcePatch(BaseModel):
    enabled: bool


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    platform: Platform
    display_name: str
    enabled: bool
    status: str
    capabilities: list[str]
    last_checked_at: datetime | None
    last_error: str | None
    mode: str
    diagnostic: str


class SearchResponse(BaseModel):
    search_id: str
    result_count: int
    items: list[ItemResponse]
    warnings: list[str]
    errors: dict[str, str]


class SearchHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    query: str
    platforms: list[str]
    status: str
    result_count: int
    warnings: list[str]
    created_at: datetime

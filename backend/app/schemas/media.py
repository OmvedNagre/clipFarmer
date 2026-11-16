from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Authorization = Literal[
    "unverified", "user_owned", "creator_authorized", "licensed", "not_authorized", "unknown"
]
Profile = Literal["original", "shorts_1080x1920", "shorts_720x1280"]


class MediaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    discovered_item_id: str | None
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str | None
    authorization_status: str
    authorization_notes: str
    source_provenance: dict
    review_status: str
    publishing_metadata: dict
    subtitle_srt: str
    archived: bool
    created_at: datetime


class MediaPatch(BaseModel):
    authorization_status: Authorization | None = None
    authorization_notes: str | None = Field(default=None, max_length=4000)
    archived: bool | None = None
    subtitle_srt: str | None = Field(default=None, max_length=100000)
    publishing_metadata: dict[str, str] | None = None

    @model_validator(mode="after")
    def metadata_bounds(self):
        if self.publishing_metadata is not None:
            if set(self.publishing_metadata) - {"title", "description", "hashtags", "hook"}:
                raise ValueError("Unknown publishing metadata field")
            if any(len(v) > 5000 for v in self.publishing_metadata.values()):
                raise ValueError("Publishing field exceeds 5000 characters")
        return self


class JobRequest(BaseModel):
    media_id: str
    profiles: list[Profile] = Field(
        default=["original", "shorts_1080x1920"], min_length=1, max_length=3
    )
    trim_start_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    trim_end_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    normalize_audio: bool = False
    mute_audio: bool = False
    burn_subtitles: bool = False
    crf: int = Field(default=23, ge=16, le=35)
    fps: Literal[24, 30, 60] = 30

    @model_validator(mode="after")
    def valid_trim(self):
        if self.trim_end_seconds is not None and self.trim_end_seconds <= self.trim_start_seconds:
            raise ValueError("End must follow start")
        self.profiles = list(dict.fromkeys(self.profiles))
        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    media_asset_id: str
    status: str
    progress_percent: int
    options: dict
    attempt_count: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    retryable: bool
    cancel_requested: bool
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class OutputMediaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_filename: str
    review_status: str
    authorization_status: str
    publishing_metadata: dict
    archived: bool


class OutputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    processing_job_id: str
    profile: str
    filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str | None
    sha256: str
    validation_status: str
    created_at: datetime
    media: OutputMediaResponse | None = None


class ReviewRequest(BaseModel):
    action: Literal["approved", "rejected", "needs_changes"]
    notes: str = Field(default="", max_length=4000)


class ConfirmDelete(BaseModel):
    confirm: bool = False
    delete_file: bool = False

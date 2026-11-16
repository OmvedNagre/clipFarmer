"""Pure business-rule tests: no database, web server or external API calls."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.core import security
from app.core.config import Settings, get_settings
from app.schemas.media import JobRequest, MediaPatch
from app.services.media import parse_srt, trimmed_srt


def test_caption_trim_clips_shifts_and_removes_outside_cues():
    srt = "1\n00:00:00,000 --> 00:00:01,000\nBefore\n\n2\n00:00:01,500 --> 00:00:03,500\nOverlap\n\n3\n00:00:04,000 --> 00:00:05,000\nAfter\n"
    assert trimmed_srt(srt, 2, 3) == "1\n00:00:00,000 --> 00:00:01,000\nOverlap\n"


def test_caption_markup_cannot_inject_ass_commands():
    cues = parse_srt("1\n00:00:00,000 --> 00:00:01,000\n<b>Hello</b> {\\pos(0,0)}world")
    assert cues == [(0, 1, "Hello world")]


@pytest.mark.parametrize(
    "text",
    [
        "garbage",
        "1\n00:00:02,000 --> 00:00:01,000\nBackwards",
        "1\n00:60:00,000 --> 01:01:00,000\nBad minute",
    ],
)
def test_bad_captions_are_rejected(text):
    with pytest.raises(HTTPException) as exc:
        parse_srt(text)
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    "options",
    [
        {"trim_start_seconds": float("nan")},
        {"trim_end_seconds": float("inf")},
        {"trim_start_seconds": 2, "trim_end_seconds": 1},
        {"fps": 25},
        {"crf": 51},
        {"profiles": []},
    ],
)
def test_invalid_encoding_options_are_rejected(options):
    with pytest.raises(ValidationError):
        JobRequest(media_id="asset", **options)


def test_metadata_rejects_unknown_fields_and_oversize_copy():
    for metadata in [{"token": "secret"}, {"title": "x" * 5001}]:
        with pytest.raises(ValidationError):
            MediaPatch(publishing_metadata=metadata)


def test_production_requires_strong_authentication():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", app_access_token="short")


def test_session_tampering_expiry_and_clock_skew(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_access_token", SecretStr("unit-test-key"))
    monkeypatch.setattr(security.time, "time", lambda: 100000)
    cookie = security.session_cookie()

    def request(value):
        return SimpleNamespace(headers={}, cookies={"clipforge_session": value})

    assert security.authorized(request(cookie))
    assert not security.authorized(request(cookie + "tampered"))
    monkeypatch.setattr(security.time, "time", lambda: 100000 + 43200)
    assert not security.authorized(request(cookie))
    monkeypatch.setattr(security.time, "time", lambda: 99999)
    assert not security.authorized(request(cookie))


def test_non_ascii_bearer_is_rejected_without_crashing(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_access_token", SecretStr("unit-test-key"))
    assert not security.authorized(
        SimpleNamespace(headers={"authorization": "Bearer 🔑"}, cookies={})
    )

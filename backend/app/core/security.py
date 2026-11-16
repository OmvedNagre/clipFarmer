import hashlib
import hmac
import time

from fastapi import HTTPException

from app.core.config import get_settings


def session_cookie():
    stamp = str(int(time.time()))
    key = get_settings().app_access_token.get_secret_value().encode()
    return stamp + "." + hmac.new(key, stamp.encode(), hashlib.sha256).hexdigest()


def authorized(request):
    key = get_settings().app_access_token.get_secret_value()
    if not key:
        return True
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer ") and hmac.compare_digest(
        header[7:].encode("utf-8"), key.encode("utf-8")
    ):
        return True
    cookie = request.cookies.get("clipforge_session", "")
    try:
        stamp, signature = cookie.split(".", 1)
        return 0 <= time.time() - int(stamp) < 43200 and hmac.compare_digest(
            signature, hmac.new(key.encode(), stamp.encode(), hashlib.sha256).hexdigest()
        )
    except (ValueError, TypeError):
        return False


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = (
            (get_settings().max_upload_mb + 1) * 1024 * 1024
            if scope["path"].endswith("/media/upload")
            else 1024 * 1024
        )
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                raise HTTPException(413, "Request exceeds the configured size limit.")
            return message

        await self.app(scope, limited_receive, send)

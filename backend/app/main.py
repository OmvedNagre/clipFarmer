import hmac
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.adapters.live import ConnectorError
from app.adapters.registry import PLATFORMS, get_adapter
from app.api.delivery import router as delivery_router
from app.api.media import processing_stats
from app.api.media import router as media_router
from app.core.config import get_settings
from app.core.security import UploadLimitMiddleware, authorized, session_cookie
from app.db.session import SessionLocal, get_db
from app.models import (
    DiscoveredItem,
    DiscoverySearch,
    MediaAsset,
    PlatformSource,
    SearchResult,
    utcnow,
)
from app.schemas import (
    ItemResponse,
    Platform,
    SearchHistoryResponse,
    SearchRequest,
    SearchResponse,
    SourcePatch,
    SourceResponse,
)
from app.services.discovery import discover
from app.services.processing import Worker, capabilities

settings = get_settings()


@asynccontextmanager
async def lifespan(app):
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        # Schema is managed by Alembic, never implicitly created on startup.
        for platform, name in PLATFORMS.items():
            source = db.scalar(select(PlatformSource).where(PlatformSource.platform == platform))
            if source is None:
                source = PlatformSource(platform=platform, display_name=name)
                db.add(source)
            health = await get_adapter(platform, settings.platform_mode).health_check()
            source.status = health["status"]
            source.capabilities = health["capabilities"]
        db.commit()
    worker = Worker(SessionLocal)
    app.state.worker = worker
    if settings.worker_enabled:
        worker.start()
    yield
    worker.close()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(UploadLimitMiddleware)
app.include_router(media_router, prefix=settings.api_v1_prefix)
app.include_router(delivery_router, prefix=settings.api_v1_prefix)
requests_by_host = defaultdict(deque)


def error_response(request, status, code, message):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        },
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    public_paths = {
        settings.api_v1_prefix + "/health",
        settings.api_v1_prefix + "/auth/status",
        settings.api_v1_prefix + "/auth/login",
    }
    if (
        request.url.path.startswith(settings.api_v1_prefix)
        and request.url.path not in public_paths
        and request.method != "OPTIONS"
        and not authorized(request)
    ):
        return error_response(
            request, 401, "unauthorized", "Unlock this workspace with its access token."
        )
    if not settings.app_access_token.get_secret_value() and request.url.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "testserver",
    }:
        return error_response(
            request,
            403,
            "local_only",
            "Configure an access token before accessing from another hostname.",
        )
    origin = request.headers.get("origin")
    if (
        request.method in {"POST", "PATCH", "DELETE", "PUT"}
        and origin
        and origin not in settings.origins
    ):
        return error_response(
            request, 403, "invalid_origin", "This origin is not allowed to modify the workspace."
        )
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        return error_response(request, 400, "invalid_length", "Invalid request length.")
    limit = (
        (settings.max_upload_mb + 1) * 1024 * 1024
        if request.url.path.endswith("/media/upload")
        else 1024 * 1024
    )
    if content_length > limit:
        return error_response(
            request, 413, "request_too_large", "Request exceeds the configured size limit."
        )
    expensive = any(
        request.url.path.endswith(x)
        for x in [
            "/discovery/search",
            "/media/upload",
            "/processing/jobs",
            "/transcribe",
            "/suggest",
            "/auth/login",
        ]
    )
    if request.method == "POST" and expensive:
        host = request.client.host if request.client else "local"
        now = monotonic()
        window = requests_by_host[(host, request.url.path)]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= 30:
            response = error_response(
                request, 429, "rate_limited", "Too many searches. Wait one minute and try again."
            )
            response.headers["Retry-After"] = "60"
            return response
        window.append(now)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error_response(
        request,
        exc.status_code,
        "not_found" if exc.status_code == 404 else "request_failed",
        str(exc.detail),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error_response(
        request,
        422,
        "invalid_input",
        "Invalid input. Check required fields, numeric limits, and selected options.",
    )


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return error_response(
        request,
        500,
        "internal_error",
        "The request could not be completed. Check local server configuration and database migrations.",
    )


prefix = settings.api_v1_prefix


@app.get(prefix + "/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "mode": settings.platform_mode, "version": "1.0.0"}


async def source_view(source):
    health = await get_adapter(source.platform, settings.platform_mode).health_check()
    return SourceResponse(
        platform=source.platform,
        display_name=source.display_name,
        enabled=source.enabled,
        status=(source.status if health["status"] == "configured" else health["status"])
        if source.enabled
        else "disabled",
        capabilities=health["capabilities"],
        last_checked_at=source.last_checked_at,
        last_error=source.last_error,
        mode=settings.platform_mode,
        diagnostic=health["diagnostic"],
    )


@app.get(prefix + "/sources", response_model=list[SourceResponse])
async def sources(db: Session = Depends(get_db)):
    return [
        await source_view(s)
        for s in db.scalars(select(PlatformSource).order_by(PlatformSource.created_at)).all()
    ]


def find_source(db, platform):
    source = db.scalar(select(PlatformSource).where(PlatformSource.platform == platform))
    if source is None:
        raise HTTPException(404, "Connector not found")
    return source


@app.post(prefix + "/sources/{platform}/test", response_model=SourceResponse)
async def test_source(platform: Platform, db: Session = Depends(get_db)):
    source = find_source(db, platform)
    health = await get_adapter(platform, settings.platform_mode).health_check()
    source.status, source.capabilities = health["status"], health["capabilities"]
    if settings.platform_mode == "live" and health["status"] == "configured":
        try:
            await get_adapter(platform, settings.platform_mode).search("GTA VI", 1)
            source.status = "connected"
            source.last_error = None
        except ConnectorError as exc:
            source.status, source.last_error = exc.status, exc.message
        except Exception:
            source.status, source.last_error = "error", "Connection test failed. Check API access."
    source.last_checked_at = utcnow()
    db.commit()
    return await source_view(source)


@app.patch(prefix + "/sources/{platform}", response_model=SourceResponse)
async def patch_source(platform: Platform, patch: SourcePatch, db: Session = Depends(get_db)):
    source = find_source(db, platform)
    source.enabled = patch.enabled
    db.commit()
    return await source_view(source)


@app.get(prefix + "/system/status")
async def system_status(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    storage_status = "available"
    probe = settings.storage_root / f".health-{uuid4()}"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        storage_status = "unavailable"
    return {
        "database": "connected",
        "storage": storage_status,
        "worker": "running"
        if getattr(app.state, "worker", None) and app.state.worker.active
        else "stopped",
        "processing_capabilities": capabilities(),
        "mode": settings.platform_mode,
        "max_upload_mb": settings.max_upload_mb,
        "connectors": await sources(db),
        "telegram": "configured"
        if settings.telegram_bot_token.get_secret_value() and settings.telegram_chat_id
        else "not_configured",
        "ai": "configured"
        if settings.openai_api_key.get_secret_value() and settings.ai_model
        else "not_configured",
        "transcription": "configured"
        if settings.openai_api_key.get_secret_value()
        else "not_configured",
        "authentication": "token_protected"
        if settings.app_access_token.get_secret_value()
        else "local_only",
    }


@app.post(prefix + "/discovery/search", response_model=SearchResponse)
async def search(request: SearchRequest, db: Session = Depends(get_db)):
    return await discover(db, request, settings.platform_mode)


@app.get(prefix + "/discovery/searches", response_model=list[SearchHistoryResponse])
def search_history(db: Session = Depends(get_db), limit: int = Query(20, ge=1, le=100)):
    return db.scalars(
        select(DiscoverySearch).order_by(DiscoverySearch.created_at.desc()).limit(limit)
    ).all()


@app.get(prefix + "/discovery/searches/{search_id}")
def search_detail(search_id: str, db: Session = Depends(get_db)):
    search = db.get(DiscoverySearch, search_id)
    if search is None:
        raise HTTPException(404, "Search not found")
    items = db.scalars(
        select(DiscoveredItem)
        .join(SearchResult, SearchResult.item_id == DiscoveredItem.id)
        .where(SearchResult.search_id == search_id)
    ).all()
    items.sort(
        key=lambda i: (
            (i.view_count or 0) if search.filters.get("sort") == "engagement" else i.published_at
        ),
        reverse=True,
    )
    return {
        "search": SearchHistoryResponse.model_validate(search),
        "items": [ItemResponse.model_validate(i) for i in items],
    }


@app.post(prefix + "/discovery/items/{item_id}/save", response_model=ItemResponse)
def save_item(item_id: str, db: Session = Depends(get_db)):
    item = db.get(DiscoveredItem, item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    item.saved = True
    db.commit()
    return item


@app.get(prefix + "/clips", response_model=list[ItemResponse])
def clips(
    db: Session = Depends(get_db),
    q: str = Query("", max_length=200),
    platform: Platform | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
):
    stmt = select(DiscoveredItem).where(DiscoveredItem.saved.is_(True))
    if q:
        stmt = stmt.where(DiscoveredItem.title.icontains(q, autoescape=True))
    if platform:
        stmt = stmt.where(DiscoveredItem.platform == platform)
    return db.scalars(
        stmt.order_by(DiscoveredItem.created_at.desc()).offset(offset).limit(limit)
    ).all()


@app.get(prefix + "/clips/{clip_id}", response_model=ItemResponse)
def clip_detail(clip_id: str, db: Session = Depends(get_db)):
    item = db.get(DiscoveredItem, clip_id)
    if item is None or not item.saved:
        raise HTTPException(404, "Saved clip not found")
    return item


@app.get(prefix + "/stats/overview")
def overview(db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(DiscoveredItem))
    saved = db.scalar(
        select(func.count()).select_from(DiscoveredItem).where(DiscoveredItem.saved.is_(True))
    )
    searches = db.scalar(select(func.count()).select_from(DiscoverySearch))
    recent = db.scalars(
        select(DiscoveredItem).order_by(DiscoveredItem.created_at.desc()).limit(5)
    ).all()
    return {
        "discovered_items": count,
        "saved_items": saved,
        "searches": searches,
        "recent_discoveries": [ItemResponse.model_validate(i) for i in recent],
        "media_assets": db.scalar(select(func.count()).select_from(MediaAsset)),
        "processing": processing_stats(db),
    }


@app.get(prefix + "/stats/platforms")
def platform_stats(db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(DiscoveredItem.platform, func.count()).group_by(DiscoveredItem.platform)
        ).all()
    )
    return [{"platform": p, "count": counts.get(p, 0)} for p in PLATFORMS]


class LoginRequest(BaseModel):
    token: SecretStr


@app.get(prefix + "/auth/status")
def auth_status(request: Request):
    return {
        "required": bool(settings.app_access_token.get_secret_value()),
        "authenticated": authorized(request),
    }


@app.post(prefix + "/auth/login")
def login(payload: LoginRequest):
    if not settings.app_access_token.get_secret_value() or not hmac.compare_digest(
        payload.token.get_secret_value().encode("utf-8"),
        settings.app_access_token.get_secret_value().encode("utf-8"),
    ):
        raise HTTPException(401, "Invalid workspace access token.")
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        "clipforge_session",
        session_cookie(),
        httponly=True,
        samesite="strict",
        secure=settings.app_env == "production",
        max_age=43200,
    )
    return response


@app.post(prefix + "/auth/logout")
def logout():
    response = JSONResponse({"authenticated": False})
    response.delete_cookie("clipforge_session")
    return response


# Production bundle is optional in development; mounted after API routes.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

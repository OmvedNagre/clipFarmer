import asyncio

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.adapters.live import ConnectorError
from app.adapters.registry import get_adapter
from app.models import DiscoveredItem, DiscoverySearch, PlatformSource, SearchResult, utcnow
from app.schemas import ItemResponse, SearchResponse


async def discover(db, request, mode):
    search = DiscoverySearch(
        query=request.query,
        platforms=request.platforms,
        filters={"sort": request.sort, "limit_per_platform": request.limit},
    )
    db.add(search)
    db.flush()
    errors, items = {}, []
    sources = {s.platform: s for s in db.scalars(select(PlatformSource)).all()}
    # Release SQLite write lock before waiting on external platform APIs.
    db.commit()

    async def run(platform):
        if not sources[platform].enabled:
            return platform, None, "Connector is disabled. Enable it in Integrations."
        try:
            result = await asyncio.wait_for(
                get_adapter(platform, mode).search(request.query, request.limit, sort=request.sort),
                timeout=45,
            )
            sources[platform].status = "connected"
            sources[platform].last_error = None
            sources[platform].last_checked_at = utcnow()
            return platform, result, None
        except ConnectorError as exc:
            sources[platform].status = exc.status
            sources[platform].last_error = exc.message
            return platform, None, exc.message
        except Exception:
            return platform, None, "Search unavailable. Check connector setup and try again."

    for platform, results, error in await asyncio.gather(*(run(p) for p in request.platforms)):
        if error:
            errors[platform] = error
            continue
        for result in results:
            item = db.scalar(
                select(DiscoveredItem).where(
                    DiscoveredItem.platform == platform,
                    DiscoveredItem.external_id == result.external_id,
                )
            )
            if item is None:
                data = result.model_dump()
                data["canonical_url"] = str(result.canonical_url)
                item = DiscoveredItem(**data, discovery_search_id=search.id)
                try:
                    with db.begin_nested():
                        db.add(item)
                        db.flush()
                except IntegrityError:
                    item = db.scalar(
                        select(DiscoveredItem).where(
                            DiscoveredItem.platform == platform,
                            DiscoveredItem.external_id == result.external_id,
                        )
                    )
            db.add(SearchResult(search_id=search.id, item_id=item.id))
            items.append(item)
    items.sort(
        key=lambda i: (i.view_count or 0) if request.sort == "engagement" else i.published_at,
        reverse=True,
    )
    search.result_count = len(items)
    search.warnings = [f"{p}: {e}" for p, e in errors.items()]
    search.status = "partial" if errors and items else "failed" if errors else "completed"
    search.completed_at = utcnow()
    db.commit()
    return SearchResponse(
        search_id=search.id,
        result_count=len(items),
        items=[ItemResponse.model_validate(i) for i in items],
        warnings=search.warnings,
        errors=errors,
    )

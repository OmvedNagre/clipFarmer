"""Official metadata APIs only. No platform media acquisition or scraping."""

import asyncio
import html
import random
import re
from datetime import UTC, datetime

import httpx

from app.adapters.base import PlatformAdapter
from app.core.config import get_settings
from app.schemas import DiscoveredItemCreate


class ConnectorError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


async def request_json(method, url, **kwargs):
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        for attempt in range(3):
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt < 2:
                    await asyncio.sleep(0.3 * 2**attempt + random.random() * 0.2)
                    continue
                raise ConnectorError(
                    "temporarily_unavailable", "Network request failed. Try again later."
                ) from None
            if response.status_code == 429:
                raise ConnectorError(
                    "rate_limited",
                    "Platform quota or rate limit reached. Wait before searching again.",
                )
            if response.status_code in {401, 403}:
                raise ConnectorError(
                    "approval_required",
                    "Credentials, plan, or granted scopes do not permit this request.",
                )
            if response.status_code >= 500 and attempt < 2:
                await asyncio.sleep(0.3 * 2**attempt + random.random() * 0.2)
                continue
            if response.is_error:
                raise ConnectorError(
                    "error", "Platform rejected this request. Check the connector configuration."
                )
            try:
                return response.json()
            except ValueError:
                raise ConnectorError("error", "Platform returned an invalid response.") from None


def date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(UTC)


def duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    return (
        sum(int(n or 0) * factor for n, factor in zip(match.groups(), [3600, 60, 1]))
        if match
        else None
    )


class LiveAdapter(PlatformAdapter):
    required = ()
    platform = ""

    async def health_check(self):
        settings = get_settings()
        configured = all(
            bool(v.get_secret_value() if hasattr(v, "get_secret_value") else v)
            for v in [getattr(settings, k) for k in self.required]
        )
        return {
            "status": "configured" if configured else "not_configured",
            "capabilities": ["search_metadata"] if configured else [],
            "diagnostic": "Official metadata API configured; use Test connector to verify access."
            if configured
            else "Set " + ", ".join(k.upper() for k in self.required) + " in .env and restart.",
        }

    async def get_item(self, external_id):
        return None

    async def ensure_configured(self):
        health = await self.health_check()
        if health["status"] != "configured":
            raise ConnectorError(health["status"], health["diagnostic"])


class YouTubeAdapter(LiveAdapter):
    platform = "youtube"
    required = ("youtube_api_key",)

    async def search(self, query, limit=20, **filters):
        await self.ensure_configured()
        key = get_settings().youtube_api_key.get_secret_value()
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": min(limit, 50),
            "key": key,
            "order": "viewCount" if filters.get("sort") == "engagement" else "date",
        }
        if filters.get("published_after"):
            params["publishedAfter"] = filters["published_after"].isoformat()
        if filters.get("published_before"):
            params["publishedBefore"] = filters["published_before"].isoformat()
        payload = await request_json(
            "GET", "https://www.googleapis.com/youtube/v3/search", params=params
        )
        rows = payload.get("items", [])
        ids = ",".join(r["id"]["videoId"] for r in rows)
        detail = (
            await request_json(
                "GET",
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "contentDetails,statistics", "id": ids, "key": key},
            )
            if ids
            else {}
        )
        lookup = {r["id"]: r for r in detail.get("items", [])}
        result = []
        for row in rows:
            identity = row["id"]["videoId"]
            s = row["snippet"]
            extra = lookup.get(identity, {})
            stats = extra.get("statistics", {})
            result.append(
                DiscoveredItemCreate(
                    platform=self.platform,
                    external_id=identity,
                    title=html.unescape(s["title"]),
                    description=html.unescape(s.get("description", "")),
                    canonical_url=f"https://www.youtube.com/watch?v={identity}",
                    thumbnail_url=s.get("thumbnails", {}).get("medium", {}).get("url"),
                    creator_id=s.get("channelId"),
                    creator_name=s.get("channelTitle", "Unknown"),
                    published_at=date(s.get("publishedAt")),
                    duration_seconds=duration(extra.get("contentDetails", {}).get("duration")),
                    view_count=int(stats["viewCount"]) if "viewCount" in stats else None,
                    like_count=int(stats["likeCount"]) if "likeCount" in stats else None,
                    comment_count=int(stats["commentCount"]) if "commentCount" in stats else None,
                    raw_metadata={"demo": False},
                )
            )
        return result


class RedditAdapter(LiveAdapter):
    platform = "reddit"
    required = ("reddit_client_id", "reddit_client_secret")

    async def search(self, query, limit=20, **filters):
        await self.ensure_configured()
        s = get_settings()
        headers = {"User-Agent": s.reddit_user_agent}
        auth = await request_json(
            "POST",
            "https://www.reddit.com/api/v1/access_token",
            auth=(s.reddit_client_id, s.reddit_client_secret.get_secret_value()),
            data={"grant_type": "client_credentials"},
            headers=headers,
        )
        headers["Authorization"] = "Bearer " + auth["access_token"]
        data = await request_json(
            "GET",
            "https://oauth.reddit.com/search",
            params={
                "q": query,
                "limit": limit,
                "sort": "top" if filters.get("sort") == "engagement" else "new",
                "type": "link",
                "raw_json": 1,
            },
            headers=headers,
        )
        return [
            DiscoveredItemCreate(
                platform=self.platform,
                external_id=d["id"],
                title=d["title"],
                description=d.get("selftext", "")[:3000],
                canonical_url="https://www.reddit.com" + d["permalink"],
                thumbnail_url=d.get("thumbnail")
                if d.get("thumbnail", "").startswith("https://")
                else None,
                creator_name=d.get("author", "Unknown"),
                published_at=datetime.fromtimestamp(d["created_utc"], UTC),
                comment_count=d.get("num_comments"),
                raw_metadata={
                    "demo": False,
                    "score": d.get("score"),
                    "subreddit": d.get("subreddit"),
                },
            )
            for d in [r["data"] for r in data.get("data", {}).get("children", [])]
        ]


class TwitchAdapter(LiveAdapter):
    platform = "twitch"
    required = ("twitch_client_id", "twitch_client_secret")

    async def search(self, query, limit=20, **filters):
        await self.ensure_configured()
        s = get_settings()
        token = await request_json(
            "POST",
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": s.twitch_client_id,
                "client_secret": s.twitch_client_secret.get_secret_value(),
                "grant_type": "client_credentials",
            },
        )
        headers = {
            "Client-Id": s.twitch_client_id,
            "Authorization": "Bearer " + token["access_token"],
        }
        # Helix has category search, not global clip keyword search. Query is a game/category name.
        games = await request_json(
            "GET",
            "https://api.twitch.tv/helix/search/categories",
            params={"query": query, "first": 1},
            headers=headers,
        )
        if not games.get("data"):
            return []
        params = {"game_id": games["data"][0]["id"], "first": limit}
        for field, source in [("started_at", "published_after"), ("ended_at", "published_before")]:
            if filters.get(source):
                params[field] = filters[source].isoformat()
        clips = await request_json(
            "GET", "https://api.twitch.tv/helix/clips", params=params, headers=headers
        )
        return [
            DiscoveredItemCreate(
                platform=self.platform,
                external_id=c["id"],
                title=c["title"],
                canonical_url=c["url"],
                thumbnail_url=c.get("thumbnail_url"),
                creator_id=c.get("creator_id"),
                creator_name=c.get("creator_name", "Unknown"),
                published_at=date(c.get("created_at")),
                duration_seconds=int(c.get("duration", 0)),
                view_count=c.get("view_count"),
                raw_metadata={
                    "demo": False,
                    "category": games["data"][0]["name"],
                    "search_scope": "category_clips",
                },
            )
            for c in clips.get("data", [])
        ]


class XAdapter(LiveAdapter):
    platform = "x"
    required = ("x_bearer_token",)

    async def search(self, query, limit=20, **filters):
        await self.ensure_configured()
        params = {
            "query": query,
            "max_results": max(10, limit),
            "tweet.fields": "created_at,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "username",
            "sort_order": "relevancy" if filters.get("sort") == "engagement" else "recency",
        }
        for field, source in [("start_time", "published_after"), ("end_time", "published_before")]:
            if filters.get(source):
                params[field] = filters[source].isoformat()
        data = await request_json(
            "GET",
            "https://api.x.com/2/tweets/search/recent",
            params=params,
            headers={"Authorization": "Bearer " + get_settings().x_bearer_token.get_secret_value()},
        )
        users = {
            u["id"]: u.get("username", "Unknown") for u in data.get("includes", {}).get("users", [])
        }
        return [
            DiscoveredItemCreate(
                platform=self.platform,
                external_id=t["id"],
                title=t["text"][:200],
                description=t["text"],
                canonical_url=f"https://x.com/i/web/status/{t['id']}",
                creator_id=t.get("author_id"),
                creator_name=users.get(t.get("author_id"), "Unknown"),
                published_at=date(t.get("created_at")),
                view_count=t.get("public_metrics", {}).get("impression_count"),
                like_count=t.get("public_metrics", {}).get("like_count"),
                comment_count=t.get("public_metrics", {}).get("reply_count"),
                raw_metadata={"demo": False},
            )
            for t in data.get("data", [])[:limit]
        ]

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from app.adapters.base import PlatformAdapter
from app.schemas import DiscoveredItemCreate

PLATFORMS = {
    "youtube": "YouTube",
    "reddit": "Reddit",
    "twitch": "Twitch",
    "tiktok": "TikTok",
    "x": "X",
    "instagram": "Instagram",
}
URLS = {
    "youtube": "https://www.youtube.com/",
    "reddit": "https://www.reddit.com/",
    "twitch": "https://www.twitch.tv/",
    "tiktok": "https://www.tiktok.com/",
    "x": "https://x.com/",
    "instagram": "https://www.instagram.com/",
}
TOPICS = [
    "Vice City after dark",
    "World details worth a closer look",
    "The road to Leonida",
    "Trailer breakdown",
    "Community theories",
    "Scenes from the coast",
]


class MockAdapter(PlatformAdapter):
    def __init__(self, platform):
        self.platform = platform

    async def health_check(self):
        return {
            "status": "connected",
            "capabilities": ["search_metadata"],
            "diagnostic": "DEMO · deterministic sample data; no live API connection.",
        }

    async def search(self, query, limit=20, **filters):
        digest = sha256(query.casefold().encode()).hexdigest()[:12]
        return [self.make_item(f"demo-{digest}-{index}", query, index) for index in range(limit)]

    def make_item(self, external_id, query, index):
        return DiscoveredItemCreate(
            platform=self.platform,
            external_id=external_id,
            title=f"{query} · {TOPICS[index % len(TOPICS)]}",
            description="DEMO fixture for testing the discovery workflow. This is not a real post or an available video file.",
            canonical_url=URLS[self.platform],
            creator_name=f"Demo creator {index + 1:02d}",
            published_at=datetime(2026, 1, 1, tzinfo=UTC) - timedelta(hours=index * 6),
            duration_seconds=25 + index * 3,
            view_count=1200 + index * 317,
            raw_metadata={"demo": True, "source_link_type": "platform_homepage"},
        )

    async def get_item(self, external_id):
        return None  # Saved normalized records are served by the application database.


class UnavailableAdapter(PlatformAdapter):
    def __init__(self, platform):
        self.platform = platform

    async def health_check(self):
        return {
            "status": "approval_required"
            if self.platform in {"tiktok", "instagram"}
            else "not_configured",
            "capabilities": [],
            "diagnostic": "Approved discovery access is required. Submit a source URL and authorized file instead; no scraping is performed.",
        }

    async def search(self, query, limit=20, **filters):
        raise RuntimeError("Live connector unavailable")

    async def get_item(self, external_id):
        return None


def get_adapter(platform, mode="mock") -> PlatformAdapter:
    if platform not in PLATFORMS:
        raise ValueError("Unsupported platform")
    if mode == "mock":
        return MockAdapter(platform)
    from app.adapters.live import RedditAdapter, TwitchAdapter, XAdapter, YouTubeAdapter

    registry = {
        "youtube": YouTubeAdapter,
        "reddit": RedditAdapter,
        "twitch": TwitchAdapter,
        "x": XAdapter,
    }
    return registry[platform]() if platform in registry else UnavailableAdapter(platform)

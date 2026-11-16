from abc import ABC, abstractmethod

from app.schemas import DiscoveredItemCreate


class PlatformAdapter(ABC):
    platform: str

    @abstractmethod
    async def health_check(self) -> dict: ...

    @abstractmethod
    async def search(
        self, query: str, limit: int = 20, **filters
    ) -> list[DiscoveredItemCreate]: ...

    @abstractmethod
    async def get_item(self, external_id: str) -> DiscoveredItemCreate | None: ...

from __future__ import annotations

from typing import Protocol

from LiveNotifyUID.types import LiveStatus


class ProviderError(RuntimeError):
    """Raised when a platform provider cannot produce a live status."""


class LiveProvider(Protocol):
    async def check_channel(self, external_id: str, timeout_seconds: float) -> LiveStatus:
        """Fetch and normalize live status for one platform channel."""

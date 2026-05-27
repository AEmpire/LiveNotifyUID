from __future__ import annotations

from typing import Protocol

from LiveNotifyUID.types import LiveStatus


class ProviderError(RuntimeError):
    """Raised when a platform provider cannot produce a live status.

    status_code (optional) lets schedulers distinguish actionable HTTP
    failures (429 rate-limited, 403 quota/permission denied, etc.) from
    generic parsing / network failures so they can alert the user instead
    of silently retrying forever.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LiveProvider(Protocol):
    async def check_channel(self, external_id: str, timeout_seconds: float) -> LiveStatus:
        """Fetch and normalize live status for one platform channel."""

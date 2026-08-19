"""Monotonic request-deadline propagation for bounded backend work."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


class DeadlineExceeded(TimeoutError):
    """Raised when the request's internal execution budget is exhausted."""


@dataclass(frozen=True, slots=True)
class Deadline:
    """An absolute monotonic deadline safe from wall-clock adjustments."""

    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> "Deadline":
        return cls(expires_at=monotonic() + seconds)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining_seconds <= 0

    def raise_if_expired(self) -> None:
        if self.expired:
            raise DeadlineExceeded("request deadline exceeded")

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Run an async operation inside the remaining request budget."""

        self.raise_if_expired()
        try:
            async with asyncio.timeout(self.remaining_seconds):
                return await operation()
        except TimeoutError as exc:
            raise DeadlineExceeded("request deadline exceeded") from exc


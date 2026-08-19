"""HyperCLOVA X interface only; no external HTTP call exists in this phase."""

from typing import Protocol

from app.core.config import Settings


class HCXUnavailableError(RuntimeError):
    """Raised when generation is unavailable or intentionally unimplemented."""


class HCXClient(Protocol):
    async def generate(self, prompt: str) -> str: ...


class SkeletonHCXClient:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def generate(self, prompt: str) -> str:
        del prompt
        raise HCXUnavailableError(self._reason)


def build_hcx_client(settings: Settings) -> HCXClient:
    if not settings.hcx_ready:
        return SkeletonHCXClient("hcx_not_configured")
    return SkeletonHCXClient("hcx_transport_not_implemented")


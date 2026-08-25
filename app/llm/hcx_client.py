"""Authenticated NAVER Cloud HyperCLOVA X Chat Completions v3 transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import SecretStr

from app.core.config import Settings


HCX_HTTP_TIMEOUT_SECONDS = 4.0
HCX_MAX_RESPONSE_BYTES = 1_000_000


class HCXUnavailableError(RuntimeError):
    """Raised when generation is unavailable or intentionally disabled."""


class HCXTransportError(RuntimeError):
    """Sanitized error that never embeds credentials or response bodies."""


class HCXClient(Protocol):
    async def generate(self, prompt: str) -> str: ...


class SkeletonHCXClient:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def generate(self, prompt: str) -> str:
        del prompt
        raise HCXUnavailableError(self._reason)


OpenUrl = Callable[..., Any]


class NaverCloudHCXClient:
    """Small non-streaming v3 client using only the Python standard library."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: SecretStr,
        timeout_seconds: float = HCX_HTTP_TIMEOUT_SECONDS,
        open_url: OpenUrl = urlopen,
    ) -> None:
        parsed = urlparse(api_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("HCX_API_URL must be an absolute HTTPS URL")
        if not 0 < timeout_seconds < 60:
            raise ValueError("HCX HTTP timeout must be between 0 and 60 seconds")
        if not api_key.get_secret_value().strip():
            raise ValueError("HCX_API_KEY must not be blank")
        self._api_url = api_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._open_url = open_url

    def __repr__(self) -> str:
        return (
            "NaverCloudHCXClient(api_url=<configured>, "
            "api_key=SecretStr('**********'))"
        )

    @staticmethod
    def _payload(prompt: str) -> bytes:
        return json.dumps(
            {
                "messages": [{"role": "user", "content": prompt}],
                "topP": 0.1,
                "topK": 0,
                "maxTokens": 256,
                "temperature": 0.0,
                "repetitionPenalty": 1.0,
                "stop": [],
                "includeAiFilters": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _request(self, prompt: str) -> Request:
        return Request(
            self._api_url,
            data=self._payload(prompt),
            headers={
                "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid4()),
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )

    @staticmethod
    def _content(document: object) -> str:
        if not isinstance(document, dict):
            raise HCXTransportError("hcx_response_shape_invalid")
        result = document.get("result")
        if not isinstance(result, dict):
            raise HCXTransportError("hcx_response_shape_invalid")
        message = result.get("message")
        if not isinstance(message, dict):
            raise HCXTransportError("hcx_response_shape_invalid")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HCXTransportError("hcx_generation_empty")
        return content

    def _generate_sync(self, prompt: str) -> str:
        request = self._request(prompt)
        try:
            with self._open_url(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = int(getattr(response, "status", 0))
                if not 200 <= status < 300:
                    raise HCXTransportError(f"hcx_http_error status={status}")
                body = response.read(HCX_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise HCXTransportError(
                f"hcx_http_error status={error.code}"
            ) from None
        except HCXTransportError:
            raise
        except (TimeoutError, URLError, OSError):
            raise HCXTransportError("hcx_connection_error") from None

        if len(body) > HCX_MAX_RESPONSE_BYTES:
            raise HCXTransportError("hcx_response_too_large")
        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HCXTransportError("hcx_malformed_json") from None
        return self._content(document)

    async def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise HCXTransportError("hcx_prompt_empty")
        return await asyncio.to_thread(self._generate_sync, prompt)


def build_hcx_client(settings: Settings) -> HCXClient:
    if not settings.hcx_ready:
        return SkeletonHCXClient("hcx_not_configured")
    assert settings.hcx_api_key is not None
    assert settings.hcx_api_url is not None
    return NaverCloudHCXClient(
        api_url=settings.hcx_api_url,
        api_key=settings.hcx_api_key,
    )


__all__ = [
    "HCXClient",
    "HCXTransportError",
    "HCXUnavailableError",
    "NaverCloudHCXClient",
    "SkeletonHCXClient",
    "build_hcx_client",
]

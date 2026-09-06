"""Authenticated NAVER Cloud HyperCLOVA X Chat Completions v3 transport."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import SecretStr

from app.core.config import Settings


HCX_HTTP_TIMEOUT_SECONDS = 8.0
HCX_MAX_RESPONSE_BYTES = 1_000_000


class HCXUnavailableError(RuntimeError):
    """Raised when generation is unavailable or intentionally disabled."""


class HCXTransportError(RuntimeError):
    """Sanitized error that never embeds credentials or response bodies."""

    def __init__(
        self,
        code: str,
        *,
        exception_class: str,
        http_status: int | None = None,
        ncp_status_code: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.exception_class = exception_class
        self.http_status = http_status
        self.ncp_status_code = ncp_status_code


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
    def _messages(prompt: str) -> list[dict[str, str]]:
        system_prefix = "[SYSTEM]\n"
        input_separator = "\n[INPUT]\n"
        if prompt.startswith(system_prefix) and input_separator in prompt:
            system_text, user_text = prompt[len(system_prefix) :].split(
                input_separator,
                maxsplit=1,
            )
            if system_text.strip() and user_text.strip():
                return [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ]
        return [{"role": "user", "content": prompt}]

    @staticmethod
    def _payload(prompt: str) -> bytes:
        return json.dumps(
            {
                "messages": NaverCloudHCXClient._messages(prompt),
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
            raise HCXTransportError(
                "HCX_RESPONSE_SHAPE_INVALID",
                exception_class="ResponseShapeError",
            )
        result = document.get("result")
        if not isinstance(result, dict):
            raise HCXTransportError(
                "HCX_RESPONSE_SHAPE_INVALID",
                exception_class="ResponseShapeError",
            )
        message = result.get("message")
        if not isinstance(message, dict):
            raise HCXTransportError(
                "HCX_RESPONSE_SHAPE_INVALID",
                exception_class="ResponseShapeError",
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HCXTransportError(
                "HCX_GENERATION_EMPTY",
                exception_class="EmptyResponseError",
            )
        return content

    @staticmethod
    def _safe_ncp_status_code(body: bytes) -> str | None:
        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(document, dict):
            return None
        status = document.get("status")
        if not isinstance(status, dict):
            return None
        code = status.get("code")
        if not isinstance(code, (str, int)):
            return None
        normalized = str(code)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", normalized):
            return None
        return normalized

    @classmethod
    def _http_error(cls, error: HTTPError) -> HCXTransportError:
        try:
            body = error.read(HCX_MAX_RESPONSE_BYTES + 1)
        except Exception:
            body = b""
        return HCXTransportError(
            "HCX_HTTP_ERROR",
            exception_class=type(error).__name__,
            http_status=int(error.code),
            ncp_status_code=cls._safe_ncp_status_code(body),
        )

    def _generate_sync(self, prompt: str) -> str:
        request = self._request(prompt)
        try:
            response = self._open_url(request, timeout=self._timeout_seconds)
        except HTTPError as error:
            raise self._http_error(error) from None
        except TimeoutError as error:
            raise HCXTransportError(
                "HCX_OPEN_TIMEOUT",
                exception_class=type(error).__name__,
            ) from None
        except URLError as error:
            reason = getattr(error, "reason", None)
            code = (
                "HCX_OPEN_TIMEOUT"
                if isinstance(reason, TimeoutError)
                else "HCX_CONNECTION_ERROR"
            )
            exception = reason if isinstance(reason, BaseException) else error
            raise HCXTransportError(
                code,
                exception_class=type(exception).__name__,
            ) from None
        except OSError as error:
            raise HCXTransportError(
                "HCX_CONNECTION_ERROR",
                exception_class=type(error).__name__,
            ) from None

        try:
            with response:
                status = int(getattr(response, "status", 0))
                body = response.read(HCX_MAX_RESPONSE_BYTES + 1)
        except TimeoutError as error:
            raise HCXTransportError(
                "HCX_READ_TIMEOUT",
                exception_class=type(error).__name__,
            ) from None
        except OSError as error:
            raise HCXTransportError(
                "HCX_RESPONSE_READ_ERROR",
                exception_class=type(error).__name__,
            ) from None

        if not 200 <= status < 300:
            raise HCXTransportError(
                "HCX_HTTP_ERROR",
                exception_class="HTTPStatusError",
                http_status=status,
                ncp_status_code=self._safe_ncp_status_code(body),
            )

        if len(body) > HCX_MAX_RESPONSE_BYTES:
            raise HCXTransportError(
                "HCX_RESPONSE_TOO_LARGE",
                exception_class="ResponseTooLargeError",
            )
        try:
            document = json.loads(body.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise HCXTransportError(
                "HCX_RESPONSE_DECODE_ERROR",
                exception_class=type(error).__name__,
            ) from None
        except json.JSONDecodeError as error:
            raise HCXTransportError(
                "HCX_RESPONSE_JSON_ERROR",
                exception_class=type(error).__name__,
            ) from None
        return self._content(document)

    async def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise HCXTransportError(
                "HCX_PROMPT_EMPTY",
                exception_class="PromptValidationError",
            )
        return await asyncio.to_thread(self._generate_sync, prompt)


def build_hcx_client(settings: Settings) -> HCXClient:
    if not settings.hcx_ready:
        return SkeletonHCXClient("hcx_not_configured")
    assert settings.hcx_api_key is not None
    assert settings.hcx_api_url is not None
    return NaverCloudHCXClient(
        api_url=settings.hcx_api_url,
        api_key=settings.hcx_api_key,
        timeout_seconds=settings.hcx_http_timeout_seconds,
    )


__all__ = [
    "HCXClient",
    "HCXTransportError",
    "HCXUnavailableError",
    "NaverCloudHCXClient",
    "SkeletonHCXClient",
    "build_hcx_client",
]

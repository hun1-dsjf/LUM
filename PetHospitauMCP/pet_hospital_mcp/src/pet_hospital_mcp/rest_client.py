"""HTTP client wrapping the Go Pet Hospital REST API.

Only ``GET /api/v1/pets`` is wrapped for now. Future tools reuse this
client by adding methods.

Responsibilities:
  * Apply a per-request timeout and a bounded retry policy on transient
    failures (timeouts, 5xx).
  * Map HTTPX / transport / HTTP / JSON-envelope failures to the unified
    :mod:`pet_hospital_mcp.errors` codes.
  * Return the ``data`` field of the Go API's unified response envelope.

The Go API envelope is::

    {"code": int, "message": str, "data": {...}, "time": "RFC3339"}

Successful HTTP responses carry the envelope ``code`` equal to the HTTP
status (the Go server writes ``code`` = HTTP status). Errors are mapped
from the HTTP status, not from ``code``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Config
from .errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    INTERNAL_ERROR,
    BackendError,
)
from .logging_config import get_logger

log = get_logger("pet_hospital_mcp.rest_client")

# HTTP statuses that are worth retrying (transient server-side failures).
_RETRYABLE_STATUS = {500, 502, 503, 504}

# Cap a single record's payload to detect grossly malformed bodies.
_MAX_PAYLOAD_BYTES = 64 * 1024 * 1024  # 64 MiB


class PetHospitalClient:
    """Async HTTP client for the Go Pet Hospital REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        retries: int = 1,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._retries = max(0, retries)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- public -------------------------------------------------------------

    async def list_pets(self, params: dict[str, Any]) -> dict[str, Any]:
        """Call ``GET /api/v1/pets`` and return the ``data`` payload.

        Raises :class:`BackendError` on any failure.
        """
        return await self._get_data("/api/v1/pets", params=params, op="list_pets")

    # -- internals ----------------------------------------------------------

    async def _get_data(
        self,
        path: str,
        *,
        params: dict[str, Any],
        op: str,
    ) -> dict[str, Any]:
        attempts = 0
        last_exc: BackendError | None = None
        max_attempts = self._retries + 1
        while attempts < max_attempts:
            attempts += 1
            try:
                resp = await self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                last_exc = BackendError(
                    BACKEND_TIMEOUT,
                    f"上游响应超时({op})",
                    details={"attempt": attempts, "timeout_s": self._timeout},
                )
                log.warning(
                    "backend timeout",
                    extra={"tool_name": op, "params": params, "status": BACKEND_TIMEOUT, "attempt": attempts},
                )
                continue  # retry
            except httpx.TransportError as exc:
                # ConnectError, ReadError, etc. → service unavailable.
                last_exc = BackendError(
                    BACKEND_UNAVAILABLE,
                    f"无法连接上游服务({op})",
                    details={"attempt": attempts, "reason": type(exc).__name__},
                )
                log.warning(
                    "backend unreachable",
                    extra={"tool_name": op, "params": params, "status": BACKEND_UNAVAILABLE, "attempt": attempts},
                )
                continue  # retry
            except httpx.HTTPError as exc:
                # Other httpx errors — non-retryable mapping.
                raise BackendError(
                    BACKEND_UNAVAILABLE,
                    f"上游通信失败({op})",
                    details={"reason": type(exc).__name__},
                )

            # We got an HTTP response.
            status = resp.status_code
            if status >= 400:
                body_text = self._safe_text(resp)
                details: dict[str, Any] = {"http_status": status}
                # Try to surface the Go API's own error message if present.
                go_msg = self._extract_go_message(body_text)
                if go_msg:
                    details["upstream_message"] = go_msg
                if status in _RETRYABLE_STATUS and attempts < max_attempts:
                    log.warning(
                        "backend retryable error",
                        extra={"tool_name": op, "params": params, "status": BACKEND_API_ERROR, "http_status": status, "attempt": attempts},
                    )
                    last_exc = BackendError(
                        BACKEND_API_ERROR,
                        f"上游返回错误状态 {status}({op})",
                        details=details,
                    )
                    continue
                raise BackendError(
                    BACKEND_API_ERROR,
                    f"上游返回错误状态 {status}({op})",
                    details=details,
                )

            # 2xx — parse JSON envelope.
            return self._parse_data(resp, op=op, params=params)

        # Exhausted retries.
        assert last_exc is not None
        raise last_exc

    # -- parsing ------------------------------------------------------------

    def _parse_data(
        self,
        resp: httpx.Response,
        *,
        op: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        raw = resp.content or b""
        if len(raw) > _MAX_PAYLOAD_BYTES:
            raise BackendError(
                BACKEND_INVALID_RESPONSE,
                f"上游响应体过大({op})",
                details={"size_bytes": len(raw)},
            )
        try:
            envelope = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise BackendError(
                BACKEND_INVALID_RESPONSE,
                f"上游响应非合法 JSON({op})",
                details={"reason": type(exc).__name__},
            ) from exc

        if not isinstance(envelope, dict):
            raise BackendError(
                BACKEND_INVALID_RESPONSE,
                f"上游响应信封不是 JSON 对象({op})",
                details={"got_type": type(envelope).__name__},
            )

        data = envelope.get("data")
        # The Go API always returns a ``data`` object for /api/v1/pets success.
        if data is None:
            # ``data`` may legitimately be ``null`` for some endpoints, but not
            # for ``GET /api/v1/pets``. Treat null/missing as malformed.
            raise BackendError(
                BACKEND_INVALID_RESPONSE,
                f"上游响应信封缺少 data 字段({op})",
                details={"envelope_keys": list(envelope.keys())},
            )
        if not isinstance(data, dict):
            raise BackendError(
                BACKEND_INVALID_RESPONSE,
                f"上游 data 不是 JSON 对象({op})",
                details={"got_type": type(data).__name__},
            )
        return data

    @staticmethod
    def _safe_text(resp: httpx.Response) -> str:
        try:
            return resp.text
        except Exception:
            return ""

    @staticmethod
    def _extract_go_message(body: str) -> str | None:
        if not body:
            return None
        try:
            parsed = json.loads(body)
        except ValueError:
            return None
        if isinstance(parsed, dict):
            msg = parsed.get("message")
            if isinstance(msg, str) and msg:
                return msg
        return None


def build_default_client(config: Config) -> PetHospitalClient:
    """Construct a production client from a :class:`Config`."""
    return PetHospitalClient(
        base_url=config.backend_base_url,
        timeout=config.backend_timeout_seconds,
        retries=config.backend_retries,
    )

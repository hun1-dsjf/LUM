"""Unified structured error model for the MCP service.

The wire shape consumed by MCP clients is::

    {
      "error": {
        "code": "ERROR_CODE",
        "message": "human-readable message",
        "details": { ... }
      }
    }

Error codes are stable identifiers; ``details`` is an arbitrary JSON-serializable
mapping with extra context (status code, request id, validation issues, ...).

Stack traces from HTTPX / Pydantic / the SDK / Python are never forwarded to the
MCP client — only the unified structure above.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- error code constants -------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
BACKEND_API_ERROR = "BACKEND_API_ERROR"
BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorBody(BaseModel):
    """The ``error`` object payload."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable error message.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured context (HTTP status, validation issues, ...).",
    )


class ErrorEnvelope(BaseModel):
    """Top-level unified error structure."""

    error: ErrorBody


class BackendError(Exception):
    """Carries a unified error payload through the tool layer.

    The tool handler catches this and converts it to a ``ToolError`` whose
    message is the JSON-serialized :class:`ErrorEnvelope`.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(error=ErrorBody(code=self.code, message=self.message, details=self.details))

    def to_json(self) -> str:
        return self.to_envelope().model_dump_json()


def validation_error(message: str, details: dict[str, Any] | None = None) -> BackendError:
    return BackendError(VALIDATION_ERROR, message, details=details)


def internal_error(message: str, details: dict[str, Any] | None = None) -> BackendError:
    return BackendError(INTERNAL_ERROR, message, details=details)

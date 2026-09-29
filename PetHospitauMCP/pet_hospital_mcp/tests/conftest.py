"""Shared pytest fixtures and helpers for the Pet Hospital MCP tests.

Tests never touch the real Go service: the backend is mocked via
``httpx.MockTransport``. The MCP server is exercised over an in-process
``httpx.ASGITransport`` with the SDK session manager explicitly entered
(``httpx.ASGITransport`` does not run the ASGI lifespan on its own).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

import httpx
import pytest

from pet_hospital_mcp import MCP_HTTP_PATH, MCP_PROTOCOL_VERSION
from pet_hospital_mcp.rest_client import PetHospitalClient
from pet_hospital_mcp.server import create_app
from pet_hospital_mcp.tools import list_pets as list_pets_mod

# 2026-07-28 per-request envelope carried inside ``params._meta``.
META: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "0.0"},
}

BASE_MCP_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
}


# ---------------------------------------------------------------------------
# Sample Go API payloads
# ---------------------------------------------------------------------------


def make_pet(**overrides: Any) -> dict[str, Any]:
    """A single Go API ``Pet`` object. ``records``/``charges`` default to
    ``None`` so we exercise the null-tolerant output model."""
    base: dict[str, Any] = {
        "id": "PET-000001",
        "name": "旺财",
        "species": "犬",
        "breed": "金毛寻回犬",
        "gender": "公",
        "ageMonths": 36,
        "color": "金黄",
        "chipNo": None,
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "ownerAddr": "北京市朝阳区",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "就诊中",
        "allergy": "无",
        "note": None,
        "records": None,
        "charges": None,
        "totalCost": 380.0,
        "visitCount": 1,
        "createdAt": "2025-01-01T10:00:00+08:00",
        "updatedAt": "2025-01-01T10:00:00+08:00",
    }
    base.update(overrides)
    return base


def go_envelope(data: Any, *, code: int = 200, message: str = "ok") -> dict[str, Any]:
    """The Go API unified response envelope."""
    return {"code": code, "message": message, "data": data, "time": "2025-01-01T10:00:00+08:00"}


def go_list_data(pets: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    """The ``data`` payload for ``GET /api/v1/pets``."""
    items = pets if pets is not None else [make_pet()]
    data: dict[str, Any] = {
        "items": items,
        "total": len(items),
        "page": 1,
        "pageSize": 20,
        "totalPages": 1,
        "totalCost": sum(p.get("totalCost", 0) for p in items),
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Backend mock transport (httpx.MockTransport)
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_requests() -> list[httpx.Request]:
    """Collects every request issued by the REST client for assertions."""
    return []


@pytest.fixture
def backend_handler_factory(captured_requests: list[httpx.Request]):
    """Returns a factory that builds a MockTransport handler.

    The factory takes a function ``fn(request) -> httpx.Response | raises``
    and wraps it so the request is also recorded in ``captured_requests``.
    """

    def _factory(responder: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return responder(request)

        return httpx.MockTransport(handler)

    return _factory


@pytest.fixture
def mock_client(backend_handler_factory, captured_requests):
    """A PetHospitalClient wired to a default 200 backend. Tests may
    re-create the client with their own handler via
    ``backend_handler_factory``."""

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=go_envelope(go_list_data()),
        )

    transport = backend_handler_factory(responder)
    client = PetHospitalClient(
        base_url="http://backend.test",
        transport=transport,
        timeout=2.0,
        retries=1,
    )
    list_pets_mod.set_client(client)
    yield client
    list_pets_mod.set_client(None)


# ---------------------------------------------------------------------------
# In-process MCP app (ASGI transport + session manager)
# ---------------------------------------------------------------------------
#
# ``httpx.ASGITransport`` does not run the ASGI lifespan, so the SDK's
# Streamable HTTP session manager must be entered explicitly. The manager's
# ``run()`` may only be entered once per instance and anyio cancel scopes must
# be entered and exited in the *same* task — therefore each test builds a
# fresh app and enters ``mcp_session`` inside its own body (not via an async
# fixture that yields across task boundaries).


@pytest.fixture
def fresh_app(mock_client):
    """A fresh ASGI app (fresh session manager) with the backend mocked via
    ``mock_client``. Tests enter :func:`mcp_session` themselves so the
    session-manager cancel scope lives entirely within one task."""
    return create_app()


@asynccontextmanager
async def mcp_session(app) -> AsyncIterator[httpx.AsyncClient]:
    """Enter the SDK session manager and yield an ``httpx.AsyncClient`` pointed
    at the in-process ASGI app. Must be used inside the test's own task."""
    async with app.mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            yield client


def build_mcp_request(
    method: str,
    *,
    params: dict[str, Any] | None = None,
    name: str | None = None,
    request_id: int = 1,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build a 2026-07-28 JSON-RPC request + required headers.

    Returns ``(json_body, headers)``. For ``tools/call`` pass ``name`` (the
    tool name) — it is placed in ``params.name`` and the ``Mcp-Name`` header.
    """
    p: dict[str, Any] = {"_meta": META}
    if name is not None:
        p["name"] = name
    if params is not None:
        p.update(params)
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": p}
    headers = {**BASE_MCP_HEADERS, "Mcp-Method": method}
    if method == "tools/call":
        # 2026-07-28 requires Mcp-Name to match params.name on tools/call.
        assert name is not None
        headers["Mcp-Name"] = name
    return body, headers


async def mcp_call(
    client: httpx.AsyncClient,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    name: str | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    """POST a 2026-07-28 request to ``/mcp`` and return the parsed JSON."""
    body, headers = build_mcp_request(
        method, params=params, name=name, request_id=request_id
    )
    resp = await client.post(MCP_HTTP_PATH, headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return json.loads(resp.text)


def text_of_content(result: dict[str, Any]) -> str:
    """Join all text content blocks of a CallToolResult."""
    parts: list[str] = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)

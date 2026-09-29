"""End-to-end MCP wire-protocol tests (SDK 2.x, 2026-07-28).

Drives a fresh ASGI app in-process via ``httpx.ASGITransport`` with the SDK
Streamable HTTP session manager entered inside each test's own task (the
manager's cancel scope cannot span tasks, and ``run()`` may only be entered
once per instance). Verifies:

  * ``/health`` returns the documented JSON payload.
  * The stateless flow sends **no** old ``initialize`` and the response
    carries **no** ``Mcp-Session-Id`` header.
  * ``server/discover`` succeeds (the 2026-07-28 discovery handshake).
  * ``tools/list`` advertises ``list_pets`` whose input schema carries the
    14 documented params (nested under the ``params`` field).
  * ``tools/call`` succeeds and returns the ``ListPetsResult`` payload.
  * ``tools/call`` with a bad input marks the call failed (``isError``)
    and surfaces the unified error JSON.

The Go backend is mocked (``fresh_app`` pulls in ``mock_client``) — the real
service is never contacted.
"""

from __future__ import annotations

import json

from pet_hospital_mcp import MCP_HTTP_PATH

from .conftest import build_mcp_request, mcp_call, mcp_session, text_of_content


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    async def test_returns_ok_payload(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["status"] == "ok"
            assert payload["service"] == "Pet Hospital MCP"
            assert payload["mcp_sdk_version"] == "2.0.0"
            assert payload["mcp_protocol_version"] == "2026-07-28"
            assert payload["transport"] == "streamable-http (stateless)"


# ---------------------------------------------------------------------------
# Stateless flow + discovery
# ---------------------------------------------------------------------------


class TestStatelessFlow:
    async def test_response_has_no_session_id(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            body, headers = build_mcp_request("server/discover")
            resp = await client.post(MCP_HTTP_PATH, headers=headers, json=body)
            assert resp.status_code == 200
            header_names = {k.lower() for k in resp.headers}
            assert "mcp-session-id" not in header_names

    async def test_discover_returns_result(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            result = await mcp_call(client, "server/discover")
            assert "result" in result
            assert "error" not in result

    async def test_no_initialize_required(self, fresh_app):
        # A tools/list issued without any prior ``initialize`` must succeed
        # (stateless mode never does the old handshake).
        async with mcp_session(fresh_app) as client:
            result = await mcp_call(client, "tools/list")
            assert "result" in result
            assert "error" not in result


# ---------------------------------------------------------------------------
# Tool discovery (registration + JSON Schema)
# ---------------------------------------------------------------------------


class TestToolDiscovery:
    async def test_list_pets_advertised(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            result = await mcp_call(client, "tools/list")
            tools = result["result"]["tools"]
            names = [t["name"] for t in tools]
            assert "list_pets" in names

    async def test_list_pets_schema_has_14_params(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            result = await mcp_call(client, "tools/list")
            tool = next(
                t for t in result["result"]["tools"] if t["name"] == "list_pets"
            )
            schema = tool["inputSchema"]
            # The ``params`` property is a $ref into ``$defs/ListPetsInput``
            # (the tool signature is ``list_pets(params: ListPetsInput)``).
            params_schema = schema["$defs"]["ListPetsInput"]
            props = params_schema["properties"]
            expected = {
                "q", "name", "ownerName", "ownerPhone", "species", "doctor",
                "disease", "status", "min", "max", "sortBy", "order",
                "page", "pageSize",
            }
            assert expected <= set(props)
            # ListPetsInput has extra="forbid" → additionalProperties: false.
            assert params_schema.get("additionalProperties") is False


# ---------------------------------------------------------------------------
# Tool call — success + failure
# ---------------------------------------------------------------------------


class TestToolCall:
    async def test_call_success_returns_data(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            result = await mcp_call(
                client,
                "tools/call",
                params={"arguments": {"params": {"page": 1, "pageSize": 20, "species": "犬"}}},
                name="list_pets",
            )
            call_result = result["result"]
            assert call_result.get("isError") is not True
            text = text_of_content(call_result)
            payload = json.loads(text)
            assert payload["total"] == 1
            assert payload["items"][0]["id"] == "PET-000001"
            assert payload["page"] == 1
            assert payload["pageSize"] == 20

    async def test_call_validation_error_marked_failed(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            result = await mcp_call(
                client,
                "tools/call",
                params={"arguments": {"params": {"species": "不存在的种类"}}},
                name="list_pets",
            )
            call_result = result["result"]
            assert call_result["isError"] is True
            text = text_of_content(call_result)
            # The SDK wraps tool exceptions as
            # ``"Error executing tool list_pets: <json envelope>"`` — strip the
            # prefix and parse the unified error structure.
            idx = text.find("{")
            assert idx != -1
            payload = json.loads(text[idx:])
            assert payload["error"]["code"] == "VALIDATION_ERROR"
            assert any(
                "species" in i for i in payload["error"]["details"].get("issues", [])
            )

    async def test_call_with_empty_params_succeeds(self, fresh_app):
        async with mcp_session(fresh_app) as client:
            result = await mcp_call(
                client,
                "tools/call",
                params={"arguments": {"params": {}}},
                name="list_pets",
            )
            call_result = result["result"]
            assert call_result.get("isError") is not True
            payload = json.loads(text_of_content(call_result))
            assert payload["total"] == 1

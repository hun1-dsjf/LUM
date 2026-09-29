"""``list_pets`` tool handler unit tests.

Drives the handler directly (not through the MCP HTTP endpoint — that's
covered by ``test_server.py``). The backend is mocked via
``httpx.MockTransport`` so the real Go service is never contacted.

Covers:
  * Success — returns a ``ListPetsResult`` and forwards every filter /
    sort / paging param to the backend.
  * Validation failures — each kind of semantic violation raises an
    exception whose ``str()`` is the unified error JSON envelope with
    ``VALIDATION_ERROR``.
  * Backend failures — 4xx, timeout, invalid JSON surface as unified
    error envelopes carrying the right ``BACKEND_*`` code.
  * Registration — ``register()`` wires the tool under the name
    ``list_pets``.
"""

from __future__ import annotations

import json
import math

import httpx
import pytest
from mcp.server import MCPServer

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    VALIDATION_ERROR,
)
from pet_hospital_mcp.rest_client import PetHospitalClient
from pet_hospital_mcp.tools import list_pets as list_pets_mod
from pet_hospital_mcp.tools.list_pets import (
    ListPetsInput,
    ListPetsResult,
    list_pets,
    register,
)

from .conftest import go_envelope, go_list_data, make_pet


# ---------------------------------------------------------------------------
# Fixture: install a custom backend handler onto the tool's client
# ---------------------------------------------------------------------------


@pytest.fixture
def install_backend(backend_handler_factory, captured_requests):
    """Return a factory ``fn(handler, *, retries=0)`` that wires a mocked
    ``PetHospitalClient`` into the ``list_pets`` module. Cleans up on
    teardown so other tests see no leaked client."""

    def _install(handler, *, retries=0) -> PetHospitalClient:
        transport = backend_handler_factory(handler)
        client = PetHospitalClient(
            base_url="http://backend.test",
            transport=transport,
            timeout=2.0,
            retries=retries,
        )
        list_pets_mod.set_client(client)
        return client

    yield _install
    list_pets_mod.set_client(None)


def _default_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=go_envelope(go_list_data()))


def _err_payload(exc: BaseException) -> dict:
    """The unified error JSON envelope carried as the raised exception's
    message (direct-call path: no SDK prefix)."""
    return json.loads(str(exc))


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


class TestSuccess:
    async def test_returns_list_pets_result(self, install_backend):
        install_backend(_default_handler)
        result = await list_pets(ListPetsInput(page=1, pageSize=20))
        assert isinstance(result, ListPetsResult)
        assert result.total == 1
        assert result.items[0].id == "PET-000001"

    async def test_forwards_all_14_params(self, install_backend, captured_requests):
        install_backend(_default_handler)
        await list_pets(
            ListPetsInput(
                q="kw",
                name="旺财",
                ownerName="张三",
                ownerPhone="13800001111",
                species="犬",
                doctor="李医生",
                disease="肠胃炎",
                status="就诊中",
                min=10.0,
                max=1000.0,
                sortBy="name",
                order="desc",
                page=3,
                pageSize=50,
            )
        )
        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req.url.path == "/api/v1/pets"
        q = req.url.params
        assert q["q"] == "kw"
        assert q["name"] == "旺财"
        assert q["ownerName"] == "张三"
        assert q["ownerPhone"] == "13800001111"
        assert q["species"] == "犬"
        assert q["doctor"] == "李医生"
        assert q["disease"] == "肠胃炎"
        assert q["status"] == "就诊中"
        assert q["min"] == "10.0"
        assert q["max"] == "1000.0"
        assert q["sortBy"] == "name"
        assert q["order"] == "desc"
        assert q["page"] == "3"
        assert q["pageSize"] == "50"

    async def test_defaults_page_and_pageSize_when_omitted(
        self, install_backend, captured_requests
    ):
        install_backend(_default_handler)
        await list_pets(ListPetsInput())
        req = captured_requests[0]
        assert req.url.params["page"] == "1"
        assert req.url.params["pageSize"] == "20"


# ---------------------------------------------------------------------------
# Validation failures → unified VALIDATION_ERROR
# ---------------------------------------------------------------------------


class TestValidationFailures:
    async def test_bad_species(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(species="不存在的种类"))
        payload = _err_payload(ei.value)
        assert payload["error"]["code"] == VALIDATION_ERROR
        issues = payload["error"]["details"]["issues"]
        assert any("species" in i for i in issues)

    async def test_bad_status(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(status="foo"))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_bad_sort_by(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(sortBy="nonexistent"))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_bad_order(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(order="sideways"))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_page_below_one(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(page=0))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_page_too_large(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(pageSize=501))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_pageSize_too_small(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(pageSize=0))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_min_greater_than_max(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(min=100.0, max=10.0))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_negative_min(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(min=-5.0))
        assert _err_payload(ei.value)["error"]["code"] == VALIDATION_ERROR

    async def test_nan_rejected(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(min=float("nan")))
        payload = _err_payload(ei.value)
        assert payload["error"]["code"] == VALIDATION_ERROR
        assert any("NaN" in i for i in payload["error"]["details"]["issues"])

    async def test_inf_rejected(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput(max=float("inf")))
        payload = _err_payload(ei.value)
        assert payload["error"]["code"] == VALIDATION_ERROR
        assert any("Infinity" in i for i in payload["error"]["details"]["issues"])

    async def test_multiple_issues_collected(self, install_backend):
        install_backend(_default_handler)
        with pytest.raises(Exception) as ei:
            await list_pets(
                ListPetsInput(species="bad", status="bad", page=-1, pageSize=999)
            )
        payload = _err_payload(ei.value)
        # All four failures must appear in the same envelope.
        assert len(payload["error"]["details"]["issues"]) >= 4


# ---------------------------------------------------------------------------
# Backend failures → unified BACKEND_* error
# ---------------------------------------------------------------------------


class TestBackendFailures:
    async def test_backend_4xx(self, install_backend):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404, json={"code": 404, "message": "not found", "data": None}
            )

        install_backend(handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput())
        payload = _err_payload(ei.value)
        assert payload["error"]["code"] == BACKEND_API_ERROR
        assert payload["error"]["details"]["http_status"] == 404

    async def test_backend_timeout(self, install_backend):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        install_backend(handler, retries=0)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput())
        assert _err_payload(ei.value)["error"]["code"] == BACKEND_TIMEOUT

    async def test_backend_invalid_json(self, install_backend):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not-json")

        install_backend(handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput())
        assert _err_payload(ei.value)["error"]["code"] == BACKEND_INVALID_RESPONSE

    async def test_backend_data_schema_mismatch(self, install_backend):
        def handler(request: httpx.Request) -> httpx.Response:
            # ``items`` is not a list → ListPetsResult validation fails →
            # BACKEND_INVALID_RESPONSE.
            return httpx.Response(
                200, json=go_envelope({"items": "oops", "total": 1})
            )

        install_backend(handler)
        with pytest.raises(Exception) as ei:
            await list_pets(ListPetsInput())
        assert _err_payload(ei.value)["error"]["code"] == BACKEND_INVALID_RESPONSE


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_under_name_list_pets(self):
        mcp = MCPServer("Probe")
        register(mcp)
        # The SDK exposes registered tools via the tool manager.
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        assert "list_pets" in tool_names

    def test_input_schema_has_14_params(self):
        mcp = MCPServer("Probe")
        register(mcp)
        tool = next(
            t for t in mcp._tool_manager.list_tools() if t.name == "list_pets"
        )
        # The tool signature is ``list_pets(params: ListPetsInput)``: the
        # ``params`` property is a $ref into ``$defs/ListPetsInput``.
        input_schema = tool.parameters
        params_schema = input_schema["$defs"]["ListPetsInput"]
        props = params_schema["properties"]
        expected = {
            "q", "name", "ownerName", "ownerPhone", "species", "doctor",
            "disease", "status", "min", "max", "sortBy", "order",
            "page", "pageSize",
        }
        assert expected <= set(props)
        # ListPetsInput has extra="forbid" → additionalProperties: false.
        assert params_schema.get("additionalProperties") is False
        # ``params`` is the single required top-level arg.
        assert input_schema.get("required") == ["params"]

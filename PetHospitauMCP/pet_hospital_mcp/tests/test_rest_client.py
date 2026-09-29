"""``PetHospitalClient`` unit tests.

The Go backend is mocked entirely via ``httpx.MockTransport`` — no real
network is ever touched. Covers:

1. Normal call — request path + all filter/sort/paging params forwarded,
   and the ``data`` payload returned verbatim.
2. 4xx → ``BACKEND_API_ERROR`` with no retry (a single attempt).
3. 5xx (retryable) → retried up to the configured budget, then
   ``BACKEND_API_ERROR``.
4. Timeout → ``BACKEND_TIMEOUT`` (retried).
5. Connect/transport error → ``BACKEND_UNAVAILABLE`` (retried).
6. Non-JSON body / missing ``data`` / non-object ``data`` →
   ``BACKEND_INVALID_RESPONSE``.
"""

from __future__ import annotations

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    BackendError,
)
from pet_hospital_mcp.rest_client import PetHospitalClient

from .conftest import go_envelope, go_list_data, make_pet


def _make_client(factory, handler, *, retries=0) -> PetHospitalClient:
    transport = factory(handler)
    return PetHospitalClient(
        base_url="http://backend.test",
        transport=transport,
        timeout=2.0,
        retries=retries,
    )


# ---------------------------------------------------------------------------
# Normal call
# ---------------------------------------------------------------------------


class TestNormalCall:
    async def test_returns_data_and_forwards_params(
        self, backend_handler_factory, captured_requests
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=go_envelope(go_list_data([make_pet(id="P1")])))

        client = _make_client(backend_handler_factory, handler)
        try:
            data = await client.list_pets(
                {
                    "page": 2,
                    "pageSize": 50,
                    "species": "犬",
                    "name": "旺财",
                    "q": "kw",
                    "ownerName": "张三",
                    "ownerPhone": "13800001111",
                    "doctor": "李医生",
                    "disease": "肠胃炎",
                    "status": "就诊中",
                    "min": 10,
                    "max": 1000,
                    "sortBy": "name",
                    "order": "desc",
                }
            )
        finally:
            await client.aclose()

        assert data["total"] == 1
        assert data["items"][0]["id"] == "P1"

        # Exactly one attempt, path + every param forwarded verbatim.
        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req.url.path == "/api/v1/pets"
        q = req.url.params
        assert q["page"] == "2"
        assert q["pageSize"] == "50"
        assert q["species"] == "犬"
        assert q["name"] == "旺财"
        assert q["q"] == "kw"
        assert q["ownerName"] == "张三"
        assert q["ownerPhone"] == "13800001111"
        assert q["doctor"] == "李医生"
        assert q["disease"] == "肠胃炎"
        assert q["status"] == "就诊中"
        assert q["min"] == "10"
        assert q["max"] == "1000"
        assert q["sortBy"] == "name"
        assert q["order"] == "desc"


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------


class TestHttpErrors:
    async def test_4xx_no_retry(self, backend_handler_factory, captured_requests):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"code": 400, "message": "bad request", "data": None}
            )

        client = _make_client(backend_handler_factory, handler, retries=2)
        try:
            with pytest.raises(BackendError) as ei:
                await client.list_pets({})
            assert ei.value.code == BACKEND_API_ERROR
            assert ei.value.details["http_status"] == 400
            assert ei.value.details["upstream_message"] == "bad request"
            # 4xx is non-retryable → exactly one attempt.
            assert len(captured_requests) == 1
        finally:
            await client.aclose()

    async def test_500_retries_then_fails(
        self, backend_handler_factory, captured_requests
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500, json={"code": 500, "message": "boom", "data": None}
            )

        client = _make_client(backend_handler_factory, handler, retries=1)
        try:
            with pytest.raises(BackendError) as ei:
                await client.list_pets({})
            assert ei.value.code == BACKEND_API_ERROR
            assert ei.value.details["http_status"] == 500
            # initial attempt + 1 retry.
            assert len(captured_requests) == 2
        finally:
            await client.aclose()

    async def test_503_then_200_recovers(
        self, backend_handler_factory, captured_requests
    ):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(
                    503, json={"code": 503, "message": "busy", "data": None}
                )
            return httpx.Response(200, json=go_envelope(go_list_data()))

        client = _make_client(backend_handler_factory, handler, retries=2)
        try:
            data = await client.list_pets({})
            assert data["total"] == 1
            assert len(captured_requests) == 2
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# Transport errors
# ---------------------------------------------------------------------------


class TestTransportErrors:
    async def test_timeout_retried_then_raised(
        self, backend_handler_factory, captured_requests
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("upstream too slow")

        client = _make_client(backend_handler_factory, handler, retries=1)
        try:
            with pytest.raises(BackendError) as ei:
                await client.list_pets({})
            assert ei.value.code == BACKEND_TIMEOUT
            assert len(captured_requests) == 2  # initial + retry
        finally:
            await client.aclose()

    async def test_connect_error_retried_then_raised(
        self, backend_handler_factory, captured_requests
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(backend_handler_factory, handler, retries=1)
        try:
            with pytest.raises(BackendError) as ei:
                await client.list_pets({})
            assert ei.value.code == BACKEND_UNAVAILABLE
            assert len(captured_requests) == 2
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# Response parsing errors
# ---------------------------------------------------------------------------


class TestParseErrors:
    async def test_non_json_body(self, backend_handler_factory):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"<html>oops</html>", headers={"content-type": "text/html"}
            )

        client = _make_client(backend_handler_factory, handler)
        try:
            with pytest.raises(BackendError) as ei:
                await client.list_pets({})
            assert ei.value.code == BACKEND_INVALID_RESPONSE
        finally:
            await client.aclose()

    async def test_missing_data_field(self, backend_handler_factory):
        def handler(request: httpx.Request) -> httpx.Response:
            # Envelope without ``data``.
            return httpx.Response(
                200, json={"code": 200, "message": "ok", "time": "2025-01-01"}
            )

        client = _make_client(backend_handler_factory, handler)
        try:
            with pytest.raises(BackendError) as ei:
                await client.list_pets({})
            assert ei.value.code == BACKEND_INVALID_RESPONSE
            assert "envelope_keys" in ei.value.details
        finally:
            await client.aclose()

    async def test_data_not_object(self, backend_handler_factory):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=go_envelope([1, 2, 3]))

        client = _make_client(backend_handler_factory, handler)
        try:
            with pytest.raises(BackendError) as ei:
                await client.list_pets({})
            assert ei.value.code == BACKEND_INVALID_RESPONSE
            assert ei.value.details["got_type"] == "list"
        finally:
            await client.aclose()

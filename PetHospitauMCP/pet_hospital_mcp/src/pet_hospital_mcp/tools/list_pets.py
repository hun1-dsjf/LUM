"""``list_pets`` MCP tool — adapts ``GET /api/v1/pets`` of the Go Pet
Hospital REST API for AI agents.

The tool:
  * Validates input strictly (enums against the real Go API values, page >= 1,
    1 <= pageSize <= 500, non-negative min/max, min <= max, rejects NaN /
    Infinity), returning a unified error structure on any semantic failure.
  * Forwards the request to the Go REST API via :class:`PetHospitalClient`
    with a timeout and bounded retry.
  * Validates the upstream ``data`` payload against
    :class:`ListPetsResult`, tolerating the Go API's real ``records`` /
    ``charges`` being ``null`` or arrays.
  * Returns the validated :class:`ListPetsResult` on success.

Only the query parameters supported by the Go API are exposed; no
adapter-private business parameters are added.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..errors import (
    BACKEND_INVALID_RESPONSE,
    INTERNAL_ERROR,
    VALIDATION_ERROR,
    BackendError,
)
from ..logging_config import get_logger
from ..rest_client import PetHospitalClient, build_default_client
from ..config import load_config

log = get_logger("pet_hospital_mcp.tools.list_pets")


# ---------------------------------------------------------------------------
# Allowed values (mirror the Go API — see internal/model/model.go and the
# /api/v1/meta endpoint).
# ---------------------------------------------------------------------------

VALID_SPECIES: frozenset[str] = frozenset(
    {"犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"}
)
VALID_STATUS: frozenset[str] = frozenset(
    {"待就诊", "就诊中", "住院中", "已康复", "慢性病随访"}
)
VALID_SORT_BY: frozenset[str] = frozenset(
    {
        "id", "name", "ownerName", "species", "doctor", "disease",
        "status", "totalCost", "visitCount", "createdAt", "updatedAt",
    }
)
VALID_ORDER: frozenset[str] = frozenset({"asc", "desc"})

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 500


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class ListPetsInput(BaseModel):
    """Input parameters for ``list_pets``.

    Every field is optional. ``extra="forbid"`` rejects unknown fields at the
    SDK schema layer; semantic checks (enum membership, numeric ranges,
    NaN/Infinity, min<=max) run inside the handler and emit the unified error
    structure.
    """

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(
        default=None,
        description="全文检索词（跨字段，空格分词 AND，含病历全文）。",
    )
    name: str | None = Field(default=None, description="宠物姓名模糊匹配。")
    ownerName: str | None = Field(default=None, description="主人姓名模糊匹配。")
    ownerPhone: str | None = Field(default=None, description="主人电话模糊匹配。")
    species: str | None = Field(
        default=None,
        description="宠物种类，精确匹配；允许值：犬/猫/兔/鸟/仓鼠/爬宠/其他。",
    )
    doctor: str | None = Field(default=None, description="医生姓名模糊匹配。")
    disease: str | None = Field(default=None, description="疾病模糊匹配。")
    status: str | None = Field(
        default=None,
        description="就诊状态，精确匹配；允许值：待就诊/就诊中/住院中/已康复/慢性病随访。",
    )
    min: float | None = Field(
        default=None,
        description="总花费下限（含），非负，不能为 NaN/Infinity。",
    )
    max: float | None = Field(
        default=None,
        description="总花费上限（含），非负，不能为 NaN/Infinity，且 >= min。",
    )
    sortBy: str | None = Field(
        default=None,
        description="排序字段；允许值：id/name/ownerName/species/doctor/disease/status/totalCost/visitCount/createdAt/updatedAt。",
    )
    order: str | None = Field(
        default=None,
        description="排序方向；允许值：asc/desc。",
    )
    page: int | None = Field(
        default=None,
        description="页码，从 1 开始；不传默认 1。",
    )
    pageSize: int | None = Field(
        default=None,
        description="每页条数，1-500；不传默认 20。",
    )

    # NOTE: NaN / Infinity / enum / range / min<=max checks are performed
    # inside the handler via ``_validate_input`` so that failures surface as
    # the unified error structure rather than being pre-empted by the SDK's
    # own model-validation error formatting.


# ---------------------------------------------------------------------------
# Output models (tolerant of the Go API's null-or-array records/charges)
# ---------------------------------------------------------------------------


class TreatmentItem(BaseModel):
    """一条消费明细（对应 Go ``Treatment``）。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    item: str = ""
    category: str | None = None
    amount: float = 0.0
    doctor: str | None = None
    date: str | None = None
    note: str | None = None


class MedicalRecordItem(BaseModel):
    """一条历史病历（对应 Go ``MedicalRecord``）。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    visitDate: str | None = None
    doctor: str | None = None
    diagnosis: str = ""
    symptoms: str | None = None
    treatment: str | None = None
    prescription: list[str] | None = None
    weightKg: float | None = None
    temperature: float | None = None
    followUp: str | None = None
    charge: float = 0.0
    createdAt: str | None = None


class PetItem(BaseModel):
    """一个宠物档案（对应 Go ``Pet``），容忍 records/charges 为 null。"""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    species: str
    breed: str | None = None
    gender: str | None = None
    ageMonths: int | None = None
    color: str | None = None
    chipNo: str | None = None
    ownerName: str | None = None
    ownerPhone: str | None = None
    ownerAddr: str | None = None
    doctor: str | None = None
    disease: str | None = None
    status: str | None = None
    allergy: str | None = None
    note: str | None = None

    # Go marshals a nil slice as JSON ``null``; accept both null and array.
    records: list[MedicalRecordItem] | None = None
    charges: list[TreatmentItem] | None = None

    totalCost: float = 0.0
    visitCount: int = 0
    createdAt: str | None = None
    updatedAt: str | None = None


class ListPetsResult(BaseModel):
    """``list_pets`` 成功输出，对应 Go API ``data`` 字段。"""

    model_config = ConfigDict(extra="allow")

    items: list[PetItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    pageSize: int = DEFAULT_PAGE_SIZE
    totalPages: int = 0
    totalCost: float = 0.0


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

# Module-level REST client (lazily built from config; tests can override).
_client: PetHospitalClient | None = None


def get_client() -> PetHospitalClient:
    """Return the module-level REST client, building it on first use."""
    global _client
    if _client is None:
        _client = build_default_client(load_config())
    return _client


def set_client(client: PetHospitalClient | None) -> None:
    """Override the REST client (used by tests). The caller owns closing it."""
    global _client
    _client = client


def _validate_input(params: ListPetsInput) -> None:
    """Run semantic checks the JSON Schema cannot express.

    Raises :class:`BackendError` (``VALIDATION_ERROR``) on any failure.
    """
    issues: list[str] = []

    if params.species is not None and params.species not in VALID_SPECIES:
        issues.append(
            f"species 必须是 {sorted(VALID_SPECIES)} 之一，收到 {params.species!r}"
        )
    if params.status is not None and params.status not in VALID_STATUS:
        issues.append(
            f"status 必须是 {sorted(VALID_STATUS)} 之一，收到 {params.status!r}"
        )
    if params.sortBy is not None and params.sortBy not in VALID_SORT_BY:
        issues.append(
            f"sortBy 必须是 {sorted(VALID_SORT_BY)} 之一，收到 {params.sortBy!r}"
        )
    if params.order is not None and params.order not in VALID_ORDER:
        issues.append(f"order 必须是 asc 或 desc，收到 {params.order!r}")

    if params.page is not None and params.page < 1:
        issues.append(f"page 必须 >= 1，收到 {params.page}")
    if params.pageSize is not None and (
        params.pageSize < MIN_PAGE_SIZE or params.pageSize > MAX_PAGE_SIZE
    ):
        issues.append(
            f"pageSize 必须在 {MIN_PAGE_SIZE}-{MAX_PAGE_SIZE} 之间，收到 {params.pageSize}"
        )

    if params.min is not None and params.min < 0:
        issues.append(f"min 不能为负数，收到 {params.min}")
    if params.max is not None and params.max < 0:
        issues.append(f"max 不能为负数，收到 {params.max}")
    if (
        params.min is not None
        and params.max is not None
        and params.min > params.max
    ):
        issues.append(f"min({params.min}) 不能大于 max({params.max})")

    # NaN/Infinity already rejected by the field validator, but double-check
    # defensively in case the value slipped through.
    for name, v in (("min", params.min), ("max", params.max)):
        if v is not None and (math.isnan(v) or math.isinf(v)):
            issues.append(f"{name} 不能为 NaN 或 Infinity")

    if issues:
        raise BackendError(
            VALIDATION_ERROR,
            "输入参数校验失败",
            details={"issues": issues},
        )


def _build_query(params: ListPetsInput) -> dict[str, Any]:
    """Translate validated input into Go API query params."""
    query: dict[str, Any] = {}
    if params.q is not None:
        query["q"] = params.q
    if params.name is not None:
        query["name"] = params.name
    if params.ownerName is not None:
        query["ownerName"] = params.ownerName
    if params.ownerPhone is not None:
        query["ownerPhone"] = params.ownerPhone
    if params.species is not None:
        query["species"] = params.species
    if params.doctor is not None:
        query["doctor"] = params.doctor
    if params.disease is not None:
        query["disease"] = params.disease
    if params.status is not None:
        query["status"] = params.status
    if params.min is not None:
        query["min"] = params.min
    if params.max is not None:
        query["max"] = params.max
    if params.sortBy is not None:
        query["sortBy"] = params.sortBy
    if params.order is not None:
        query["order"] = params.order
    query["page"] = params.page if params.page is not None else DEFAULT_PAGE
    query["pageSize"] = (
        params.pageSize if params.pageSize is not None else DEFAULT_PAGE_SIZE
    )
    return query


async def list_pets(params: ListPetsInput) -> ListPetsResult:
    """List pet records from the Pet Hospital REST API.

    用途
        查询宠物档案列表，支持过滤、排序与分页。直接适配 Go 后端
        ``GET /api/v1/pets``，不引入适配器私有业务参数。

    参数
        见 :class:`ListPetsInput`：q / name / ownerName / ownerPhone /
        species / doctor / disease / status / min / max / sortBy / order /
        page / pageSize。species/status/sortBy/order 使用真实后端允许值，
        page >= 1，1 <= pageSize <= 500，min/max 非负且 min <= max。

    适用场景
        让 AI Agent 浏览宠物档案、按主人/医生/疾病/状态筛选、按花费排序、
        分页加载，作为后续 get / update 等操作的前置检索。

    返回值
        成功：``ListPetsResult``（items / total / page / pageSize /
        totalPages / totalCost），对应 Go API 响应 ``data`` 字段；
        失败：统一错误结构 ``{"error":{"code","message","details"}}``，
        工具调用以 2.x 的 ``is_error=True`` 标记失败状态。
    """
    import time

    started = time.perf_counter()
    status = "ok"
    query: dict[str, Any] = {}
    try:
        _validate_input(params)
        query = _build_query(params)
        data = await get_client().list_pets(query)
        try:
            result = ListPetsResult.model_validate(data)
        except Exception as exc:
            raise BackendError(
                BACKEND_INVALID_RESPONSE,
                "上游 data 不符合预期数据模型",
                details={"reason": type(exc).__name__, "error": str(exc)},
            ) from exc
        return result
    except BackendError as exc:
        status = exc.code
        # Convert the unified error into a tool-error whose message IS the
        # JSON envelope (so the MCP client receives the unified structure,
        # and the call is marked failed per SDK 2.x).
        raise _tool_error(exc.to_json()) from exc
    except Exception as exc:
        status = INTERNAL_ERROR
        log.exception("list_pets internal error")
        raise _tool_error(
            BackendError(
                INTERNAL_ERROR,
                "内部错误",
                details={"reason": type(exc).__name__},
            ).to_json()
        ) from exc
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "list_pets call",
            extra={
                "tool_name": "list_pets",
                "params": _safe_params_for_log(query),
                "status": status,
                "duration_ms": duration_ms,
            },
        )


def _safe_params_for_log(query: dict[str, Any]) -> dict[str, Any]:
    """Drop values that the redactor already covers; keep the shape."""
    # The JSON logger redacts ownerPhone recursively; here we just pass the
    # forwarded query so ownerPhone is masked in logs.
    return dict(query)


# ---------------------------------------------------------------------------
# ToolError bridge — keeps the unified error JSON as the tool-error message.
# ---------------------------------------------------------------------------


def _tool_error(message: str) -> Exception:
    """Raise a tool error whose message reaches the MCP client verbatim.

    Uses ``mcp.server.mcpserver.exceptions.ToolError`` (SDK 2.x) so the message
    is not prefixed with ``Error executing tool <name>``. If that import path
    is unavailable, falls back to a plain ``RuntimeError`` (the SDK still
    marks the call as ``is_error=True`` but prefixes the message).
    """
    return _ToolErrorClass(message)


try:
    from mcp.server.mcpserver.exceptions import ToolError as _ToolErrorClass  # type: ignore
except ImportError:  # pragma: no cover — fallback if the deep path moves
    try:
        from mcp.server import ToolError as _ToolErrorClass  # type: ignore
    except ImportError:  # pragma: no cover
        class _ToolErrorClass(RuntimeError):  # type: ignore[no-redef]
            """Fallback: a RuntimeError subclass."""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp_server) -> None:
    """Register ``list_pets`` on the given ``MCPServer``."""
    mcp_server.tool(name="list_pets")(list_pets)

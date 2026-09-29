"""Pydantic model unit tests.

Covers:
  * ``ListPetsInput`` — ``extra="forbid"`` rejects unknown fields; the 14
    documented query params are all accepted; type-mismatched values are
    rejected at the schema layer.
  * ``PetItem`` — tolerates the Go API's real ``records`` / ``charges``
    being ``null`` *or* arrays, and permits unknown/extra fields.
  * ``ListPetsResult`` — round-trips a realistic Go ``data`` payload whose
    ``items`` carry null ``records`` / ``charges``.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from pet_hospital_mcp.tools.list_pets import (
    ListPetsInput,
    ListPetsResult,
    MedicalRecordItem,
    PetItem,
    TreatmentItem,
)

ALL_14_PARAMS: dict = {
    "q": "kw",
    "name": "旺财",
    "ownerName": "张三",
    "ownerPhone": "13800001111",
    "species": "犬",
    "doctor": "李医生",
    "disease": "肠胃炎",
    "status": "就诊中",
    "min": 10.0,
    "max": 1000.0,
    "sortBy": "name",
    "order": "desc",
    "page": 3,
    "pageSize": 50,
}


# ---------------------------------------------------------------------------
# ListPetsInput
# ---------------------------------------------------------------------------


class TestListPetsInput:
    def test_accepts_empty(self):
        m = ListPetsInput()
        assert m.q is None
        assert m.page is None
        assert m.pageSize is None

    def test_accepts_all_14_params(self):
        m = ListPetsInput(**ALL_14_PARAMS)
        assert m.q == "kw"
        assert m.species == "犬"
        assert m.status == "就诊中"
        assert m.sortBy == "name"
        assert m.order == "desc"
        assert m.page == 3
        assert m.pageSize == 50
        assert m.min == 10.0
        assert m.max == 1000.0

    def test_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            ListPetsInput(unknownField="x")

    def test_rejects_string_for_int_page(self):
        with pytest.raises(ValidationError):
            ListPetsInput(page="not-an-int")

    def test_rejects_string_for_float_min(self):
        with pytest.raises(ValidationError):
            ListPetsInput(min="not-a-number")

    def test_accepts_nan_at_schema_layer(self):
        # NaN is a valid float for Pydantic; the *handler* must reject it via
        # the unified error structure (see test_list_pets_tool.py).
        m = ListPetsInput(min=float("nan"))
        assert math.isnan(m.min)

    def test_accepts_inf_at_schema_layer(self):
        m = ListPetsInput(max=float("inf"))
        assert math.isinf(m.max)


# ---------------------------------------------------------------------------
# PetItem / output models
# ---------------------------------------------------------------------------


class TestPetItem:
    def test_accepts_null_records_and_charges(self):
        p = PetItem(id="P1", name="旺财", species="犬", records=None, charges=None)
        assert p.records is None
        assert p.charges is None

    def test_accepts_empty_arrays(self):
        p = PetItem(id="P1", name="旺财", species="犬", records=[], charges=[])
        assert p.records == []
        assert p.charges == []

    def test_accepts_populated_arrays(self):
        p = PetItem(
            id="P1",
            name="旺财",
            species="犬",
            records=[
                {"id": "R1", "doctor": "李医生", "diagnosis": "健康", "charge": 80.0}
            ],
            charges=[{"id": "C1", "item": "挂号", "amount": 10.0}],
        )
        assert isinstance(p.records[0], MedicalRecordItem)
        assert p.records[0].doctor == "李医生"
        assert p.records[0].charge == 80.0
        assert isinstance(p.charges[0], TreatmentItem)
        assert p.charges[0].item == "挂号"

    def test_allows_extra_fields(self):
        # Go may add fields the adapter doesn't model yet; extra="allow"
        # must not reject them.
        p = PetItem(id="P1", name="旺财", species="犬", futureField="x")
        dumped = p.model_dump()
        assert dumped["futureField"] == "x"


# ---------------------------------------------------------------------------
# ListPetsResult
# ---------------------------------------------------------------------------


class TestListPetsResult:
    def test_defaults(self):
        r = ListPetsResult()
        assert r.items == []
        assert r.total == 0
        assert r.page == 1
        assert r.pageSize == 20
        assert r.totalPages == 0
        assert r.totalCost == 0.0

    def test_validates_from_go_data_with_null_records(self):
        data = {
            "items": [
                {
                    "id": "PET-000001",
                    "name": "旺财",
                    "species": "犬",
                    "records": None,
                    "charges": None,
                    "totalCost": 380.0,
                    "visitCount": 1,
                }
            ],
            "total": 1,
            "page": 1,
            "pageSize": 20,
            "totalPages": 1,
            "totalCost": 380.0,
        }
        r = ListPetsResult.model_validate(data)
        assert r.total == 1
        assert r.items[0].id == "PET-000001"
        assert r.items[0].records is None
        assert r.items[0].charges is None
        assert r.totalCost == 380.0

    def test_validates_from_go_data_with_arrays(self):
        data = {
            "items": [
                {
                    "id": "PET-000002",
                    "name": "咪咪",
                    "species": "猫",
                    "records": [{"id": "R1", "doctor": "王", "diagnosis": "ok"}],
                    "charges": [{"id": "C1", "item": "药", "amount": 5.0}],
                    "totalCost": 5.0,
                }
            ],
            "total": 1,
            "page": 1,
            "pageSize": 20,
            "totalPages": 1,
            "totalCost": 5.0,
        }
        r = ListPetsResult.model_validate(data)
        assert r.items[0].records[0].doctor == "王"
        assert r.items[0].charges[0].item == "药"

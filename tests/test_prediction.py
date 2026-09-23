"""Regression checks for forecast math, leakage, validation and failure modes."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jsonschema import ValidationError

from backend.ai import DEFAULT_MODEL, explain, required_evidence
from backend.evaluation import evaluate
from backend.forecast import month_days, next_month, predict, select_model
from backend.importers.iek import FILES, MONTHS, import_iek
from backend.planning import plan
from backend.validation import validate_schema
from backend.workflow import approve, select_quantity


def monthly_input(rates=None):
    rates = rates if rates is not None else [1.0] * 32
    monthly = []
    month = date(2024, 1, 1)
    for rate in rates:
        monthly.append(
            {
                "sku": "A",
                "month": month.isoformat(),
                "quantity": rate * month_days(month) if rate is not None else None,
                "opening_stock": 20,
            }
        )
        month = next_month(month)
    return {
        "as_of_date": "2026-09-22",
        "warehouse_id": "synthetic",
        "data_source": "synthetic",
        "review_period_days": 14,
        "safety_stock_days": 7,
        "suppliers": [{"supplier_id": "S", "name": "Synthetic", "lead_time_days": 14}],
        "products": [
            {
                "sku": "A",
                "name": "Synthetic",
                "category": "test",
                "supplier_id": "S",
                "current_stock": 5,
                "goods_in_transit": 3,
                "growth_forecast_pct": 0,
            }
        ],
        "sales": [],
        "stockouts": [],
        "monthly_history": monthly,
    }


def recommendation(data):
    return plan(data)["recommendations"][0]


def test_exact_formula_deterministic_and_input_unchanged():
    data = monthly_input()
    original = copy.deepcopy(data)
    result = plan(data)
    assert result == plan(data)
    assert data == original
    row = result["recommendations"][0]
    assert row["recommended_quantity"] == 27
    assert row["factors"]["forecast_during_coverage"] == 28
    assert row["factors"]["safety_stock"] == 7
    assert row["diagnostics"]["validation_mae"] == 0
    validate_schema(result, "planning-result")


def test_late_transit_does_not_suppress_order_and_moq_rounding():
    data = monthly_input()
    data["products"][0]["shipments"] = [{"quantity": 3, "expected_date": "2026-12-01"}]
    assert recommendation(data)["recommended_quantity"] == 30
    data["products"][0].update(minimum_order_quantity=40, order_multiple=12)
    assert recommendation(data)["recommended_quantity"] == 48
    data["products"][0]["current_stock"] = 500
    assert recommendation(data)["recommended_quantity"] == 0


def test_missing_month_is_not_zero_demand():
    data = monthly_input()
    data["monthly_history"][-1]["quantity"] = None
    row = recommendation(data)
    assert row["factors"]["regular_daily_demand"] == 1
    assert "missing_data" in row["flags"]


def test_suspected_stockout_does_not_invent_lost_units():
    data = monthly_input()
    data["monthly_history"][-1]["opening_stock"] = 0
    row = recommendation(data)
    assert "suspected_stockout" in row["flags"]
    assert row["factors"]["estimated_lost_demand"] == 0


def test_zero_sales_with_zero_stock_are_not_evidence_of_zero_demand():
    data = monthly_input()
    data["monthly_history"][-1].update(quantity=0, opening_stock=0)
    assert recommendation(data)["factors"]["regular_daily_demand"] == 1


def test_holdout_outcomes_do_not_change_predictions():
    data = monthly_input()
    before = evaluate(data)
    for point in data["monthly_history"][-3:]:
        point["quantity"] *= 10
    after = evaluate(data)
    assert [p["predicted"] for p in before["predictions"]] == [
        p["predicted"] for p in after["predictions"]
    ]
    assert after["model_mae_units"] > before["model_mae_units"]


def test_overlapping_confirmed_stockout_days_count_once():
    data = monthly_input()
    interval = {"sku": "A", "start_date": "2026-08-01", "end_date": "2026-08-05"}
    data["stockouts"] = [interval]
    once = recommendation(data)
    data["stockouts"].append(copy.deepcopy(interval))
    assert recommendation(data)["factors"] == once["factors"]
    assert once["factors"]["estimated_lost_demand"] > 0


def test_trend_and_isolated_spike():
    points = [(date(2025, m, 1), float(m)) for m in range(1, 13)]
    assert predict("trend", points, date(2026, 1, 1)) > predict("mean6", points, date(2026, 1, 1))
    flat = [(date(2025, m, 1), 10.0 if m < 12 else 100.0) for m in range(1, 13)]
    assert predict("trend", flat, date(2026, 1, 1)) == predict("mean6", flat, date(2026, 1, 1))


def test_validation_uses_past_only_and_common_origins():
    points = [(date(2025, m, 1), float(m)) for m in range(1, 13)]
    _, scores, n = select_model(points)
    expected = (
        sum(abs(predict("mean6", points[:i], points[i][0]) - points[i][1]) for i in range(6, 12))
        / 6
    )
    assert n == 6
    assert scores["mean6"] == expected
    before = predict("ses", points[:9], points[9][0])
    points[-1] = (points[-1][0], 99999.0)
    assert predict("ses", points[:9], points[9][0]) == before


def test_explicit_zeros_enable_intermittent_model():
    points = [(date(2025, m, 1), 10.0 if m % 4 == 0 else 0.0) for m in range(1, 13)]
    assert predict("tsb", points, date(2026, 1, 1)) >= 0
    assert "tsb" in select_model(points)[1]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_sku",
        "unknown_supplier",
        "future_month",
        "negative_stock",
        "nan",
        "transit_mismatch",
        "duplicate_month",
    ],
)
def test_invalid_inputs_fail(mutation):
    data = monthly_input()
    if mutation == "duplicate_sku":
        data["products"].append(copy.deepcopy(data["products"][0]))
    elif mutation == "unknown_supplier":
        data["products"][0]["supplier_id"] = "missing"
    elif mutation == "future_month":
        data["monthly_history"][-1]["month"] = "2026-09-01"
    elif mutation == "negative_stock":
        data["products"][0]["current_stock"] = -1
    elif mutation == "nan":
        data["products"][0]["growth_forecast_pct"] = float("nan")
    elif mutation == "transit_mismatch":
        data["products"][0]["shipments"] = []
    else:
        data["monthly_history"].append(copy.deepcopy(data["monthly_history"][0]))
    with pytest.raises((ValueError, ValidationError)):
        plan(data)


def test_approved_plan_is_immutable_and_approval_idempotent():
    approved = approve(plan(monthly_input()))
    assert approve(approved) == approved
    with pytest.raises(ValueError):
        select_quantity(approved, "A", 1)


def ai_client(payload, status="completed"):
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status=status, output_text=json.dumps(payload)
    )
    return client


def valid_ai():
    return {
        "evidence_keys": ["forecast_during_coverage", "current_stock"],
        "risk_code": "data_quality",
        "question_code": "confirm_stock",
    }


def test_openai_structured_output_is_grounded_and_private():
    row = recommendation(monthly_input())
    original = copy.deepcopy(row)
    client = ai_client(valid_ai())
    result = explain(row, data_source="synthetic", model="test-model", client=client)
    assert result["fallback"] is False
    assert set(required_evidence(row)) <= set(result["evidence_keys"])
    assert row == original
    request = client.responses.create.call_args.kwargs
    assert request["store"] is False
    assert request["text"]["format"]["strict"] is True
    assert set(json.loads(request["input"])) == {"factors", "context"}
    assert "sku" not in request["input"] and "stock_source" not in request["input"]


def test_default_model_is_used_when_env_override_is_absent(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    client = ai_client(valid_ai())
    result = explain(recommendation(monthly_input()), data_source="synthetic", client=client)
    assert result["fallback"] is False
    assert client.responses.create.call_args.kwargs["model"] == DEFAULT_MODEL


@pytest.mark.parametrize(
    "payload",
    [
        {
            "evidence_keys": ["invented"],
            "risk_code": "data_quality",
            "question_code": "confirm_stock",
        },
        {**valid_ai(), "recommended_quantity": 999},
        {**valid_ai(), "risk_code": "no_risk"},
        {**valid_ai(), "question_code": "Invent a supplier promise"},
        {**valid_ai(), "evidence_keys": ["current_stock", "current_stock"]},
    ],
)
def test_invalid_ai_cannot_change_plan(payload):
    row = recommendation(monthly_input())
    result = explain(row, data_source="synthetic", model="test-model", client=ai_client(payload))
    assert result["fallback"] is True
    assert row["recommended_quantity"] == 27


def test_ai_timeout_refusal_missing_key_and_partner_guard(monkeypatch):
    row = recommendation(monthly_input())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert explain(row, data_source="synthetic")["fallback_reason"] == "missing_configuration"
    client = ai_client(valid_ai())
    assert (
        explain(row, client=client, model="test")["fallback_reason"]
        == "partner_data_not_authorized"
    )
    client.responses.create.assert_not_called()
    client.responses.create.side_effect = TimeoutError()
    assert explain(row, client=client, model="test", data_source="synthetic")["fallback"]
    assert explain(row, client=ai_client({}, "incomplete"), model="test", data_source="synthetic")[
        "fallback"
    ]


def fake_workbooks(tmp_path, monkeypatch, invalid=False):
    folder = tmp_path / "IEK"
    folder.mkdir()
    for name in FILES.values():
        (folder / name).write_bytes(b"synthetic test placeholder")
    months = []
    d = date(2024, 1, 1)
    while d <= date(2026, 9, 1):
        months.append(f"{MONTHS[d.month - 1]} {d.year}")
        d = next_month(d)
    rows = {
        FILES["monthly_sales"]: [
            ("Номенклатура", "Номенклатура.Код", *months),
            (None, None, *["Количество"] * 33),
            ("Synthetic", "A", *[30] * 33),
        ],
        FILES["monthly_stock"]: [
            ("Номенклатура", "Ед.", "Номенклатура.Код", *months),
            (None, None, None, *["Количество"] * 33),
            (None, None, None, *["нач. остаток"] * 33),
            ("Synthetic", "шт", "A", *[20] * 33),
        ],
        FILES["transit"]: [
            ("Код 1с", "Артикул ИЭК", " Наименование", "поступление до 01.10.2026"),
            ("A", "article", "Synthetic", None),
            ("DUP", "article", "Synthetic", 5),
            ("DUP", "article", "Synthetic", 5),
        ],
        FILES["documents"]: [
            ("Дата", "Номер", "Документ", "Код", "Номенклатура", "Ед.", "Склад", "Количество"),
            (
                "01.08.2026 12:00:00",
                "doc1",
                "Расходная",
                "A",
                "Synthetic",
                "шт",
                "test",
                None if invalid else 30,
            ),
        ],
    }
    monkeypatch.setattr("backend.importers.iek.read_rows", lambda p: rows[p.name])
    return tmp_path


def test_importer_maps_dates_nulls_duplicate_transit_and_no_double_count(tmp_path, monkeypatch):
    folder = fake_workbooks(tmp_path, monkeypatch)
    data, audit = import_iek(folder)
    assert data["products"][0]["stock_as_of_date"] == "2026-09-01"
    assert data["monthly_history"][-1]["month"] == "2026-08-01"
    assert data["products"][0]["goods_in_transit"] == 0
    assert audit["excluded_duplicate_transit_skus"] == ["DUP"]
    assert "customer_id" not in data["sales"][0]
    assert "unit_price_kzt" not in data["sales"][0]
    without_documents = copy.deepcopy(data)
    without_documents["sales"] = []
    assert (
        recommendation(data)["recommended_quantity"]
        == recommendation(without_documents)["recommended_quantity"]
    )


def test_importer_missing_quantity_is_not_zero(tmp_path, monkeypatch):
    folder = fake_workbooks(tmp_path, monkeypatch, invalid=True)
    with pytest.raises(ValueError, match="consistent document"):
        import_iek(folder)


def test_importer_requires_four_sources(tmp_path):
    with pytest.raises(ValueError, match="Required workbook"):
        import_iek(Path(tmp_path))

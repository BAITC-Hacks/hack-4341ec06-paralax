"""Acceptance regressions for complete stockouts and explanatory completeness."""

import copy

import pytest

from backend.ai import explain, required_evidence
from backend.planning import history, plan
from scripts.benchmark_openai import cases
from tests.test_prediction import ai_client, valid_ai


def test_full_stockout_estimate_and_no_double_count():
    data = cases()["stockout"]["planning_input"]
    points, lost, _, flags, _ = history(data, "stockout")
    assert points[-1][1] is None
    assert lost == 62
    assert "stockout_adjustment" in flags
    assert plan(data)["recommendations"][0]["recommended_quantity"] == 60
    raw = copy.deepcopy(data)
    raw["stockouts"] = []
    raw["monthly_history"][-1]["opening_stock"] = 100
    assert plan(raw)["recommendations"][0]["recommended_quantity"] < 60


def test_full_stockout_with_positive_sales_rejected():
    data = cases()["stockout"]["planning_input"]
    data["monthly_history"][-1]["quantity"] = 1
    with pytest.raises(ValueError, match="positive monthly sales"):
        plan(data)


def test_initial_stockout_does_not_use_later_observations():
    data = cases()["stockout"]["planning_input"]
    data["stockouts"] = [{"sku": "stockout", "start_date": "2025-07-01", "end_date": "2025-07-31"}]
    data["monthly_history"][0]["quantity"] = 0
    _, lost, _, _, warnings = history(data, "stockout")
    assert lost == 0
    assert any("нет предыстории" in warning for warning in warnings)


@pytest.mark.parametrize("name", ["stable", "trend", "seasonal", "spike", "stockout"])
def test_ai_and_fallback_include_formula_and_applied_adjustments(name):
    row = cases()[name]["algorithm"]
    original = copy.deepcopy(row)
    payload = {
        **valid_ai(),
        "risk_code": "data_quality" if "missing_data" in row["flags"] else "review_inputs",
    }
    live = explain(row, data_source="synthetic", client=ai_client(payload))
    fallback = explain(row)
    assert not live["fallback"]
    assert fallback["fallback"]
    for result in [live, fallback]:
        assert set(required_evidence(row)) <= set(result["evidence_keys"])
        for warning in row["diagnostics"]["quality_warnings"]:
            assert warning in result["risk"]
    assert row == original

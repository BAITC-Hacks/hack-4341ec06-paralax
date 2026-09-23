"""Executable product promises; currently xfail only while modules do not exist.

Remove each xfail marker when its feature is implemented. Assertion failures then block CI.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

INPUT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "planning-input.sample.json"
PENDING = pytest.mark.xfail(
    raises=ModuleNotFoundError,
    strict=True,
    reason="Planning/workflow modules have not been implemented by the team yet",
)


def sample_input() -> dict:
    return json.loads(INPUT_FIXTURE.read_text(encoding="utf-8"))


def row(result: dict, sku: str) -> dict:
    return next(item for item in result["recommendations"] if item["sku"] == sku)


@PENDING
def test_goods_in_transit_cannot_increase_order() -> None:
    from backend.planning import plan

    baseline = sample_input()
    increased = copy.deepcopy(baseline)
    increased["products"][0]["goods_in_transit"] += 20
    before = row(plan(baseline), "CABLE-01")
    after = row(plan(increased), "CABLE-01")
    assert after["recommended_quantity"] <= before["recommended_quantity"]


@PENDING
def test_one_off_sale_is_flagged_and_does_not_dominate_regular_demand() -> None:
    from backend.planning import plan

    baseline = sample_input()
    without_bulk = copy.deepcopy(baseline)
    without_bulk["sales"] = [
        sale for sale in baseline["sales"] if sale["document_id"] != "demo-bulk"
    ]
    with_bulk_result = row(plan(baseline), "CABLE-01")
    without_bulk_result = row(plan(without_bulk), "CABLE-01")
    assert "one_off_sale" in with_bulk_result["flags"]
    assert with_bulk_result["factors"]["regular_daily_demand"] <= (
        2 * without_bulk_result["factors"]["regular_daily_demand"]
    )


@PENDING
def test_confirmed_stockout_increases_estimated_demand() -> None:
    from backend.planning import plan

    with_stockout = sample_input()
    without_stockout = copy.deepcopy(with_stockout)
    without_stockout["stockouts"] = []
    before = row(plan(without_stockout), "LAMP-02")
    after = row(plan(with_stockout), "LAMP-02")
    assert after["factors"]["estimated_lost_demand"] > 0
    assert (
        after["factors"]["forecast_during_coverage"] > before["factors"]["forecast_during_coverage"]
    )


@PENDING
def test_two_repeated_high_seasons_raise_high_season_forecast() -> None:
    from backend.planning import plan

    fixture = sample_input()
    fixture["products"] = [fixture["products"][0]]
    fixture["suppliers"] = [fixture["suppliers"][0]]
    fixture["stockouts"] = []
    fixture["sales"] = [
        {
            "date": f"{year}-{month:02d}-01",
            "sku": "CABLE-01",
            "quantity": 30 if month == 6 else 3,
            "document_id": f"demo-{year}-{month}",
        }
        for year in (2024, 2025)
        for month in range(1, 13)
    ]
    high = copy.deepcopy(fixture)
    high["as_of_date"] = "2026-05-20"
    low = copy.deepcopy(fixture)
    low["as_of_date"] = "2026-11-20"
    assert (
        row(plan(high), "CABLE-01")["factors"]["forecast_during_coverage"]
        > row(plan(low), "CABLE-01")["factors"]["forecast_during_coverage"]
    )


@PENDING
def test_manual_edit_preserves_recommendation_until_explicit_approval() -> None:
    from backend.planning import plan
    from backend.workflow import approve, select_quantity

    draft = plan(sample_input())
    original = row(draft, "CABLE-01")["recommended_quantity"]
    edited = select_quantity(draft, "CABLE-01", original + 2)
    assert edited["status"] == "draft"
    assert row(edited, "CABLE-01")["recommended_quantity"] == original
    assert row(edited, "CABLE-01")["selected_quantity"] == original + 2
    assert approve(edited)["status"] == "approved"

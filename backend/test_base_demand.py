"""Synthetic checks for Stage-2 weighting, fallbacks and confidence."""

import unittest

from base_demand import calculate
from clean_demand import MONTHS, SOURCE_COMMIT


def history(values: dict[str, float | None], adjustments: dict[str, float] | None = None) -> dict:
    adjustments = adjustments or {}
    periods = []
    for month in MONTHS:
        value = values.get(month)
        periods.append({
            "period": month, "clean_demand": value, "raw_sales": value,
            "excluded_one_off": adjustments.get(month, 0),
            "estimated_lost_demand": 0, "stock": 10 if value is not None else None,
            "partial_period": month == "2026-09", "source_cells": {},
            "reasons": [],
        })
    return {"brand": "IEK", "sku": "TEST_", "source_commit": SOURCE_COMMIT,
            "name": "Synthetic", "unit": "шт", "periods": periods}


class BaseDemandTests(unittest.TestCase):
    def test_recent_six_months_give_newer_demand_more_weight(self):
        values = {f"2026-{month:02d}": value for month, value in
                  zip(range(3, 9), (10, 20, 30, 40, 50, 60))}
        result = calculate(history(values))
        self.assertEqual(result["method"], "recent_6")
        self.assertAlmostEqual(result["base_demand_monthly"], 910 / 21)
        self.assertEqual([item["raw_weight"] for item in result["selected_periods"]],
                         [1, 2, 3, 4, 5, 6])
        self.assertEqual(result["confidence"]["level"], "high")

    def test_sparse_recent_history_uses_twelve_month_fallback(self):
        values = {"2025-10": 10, "2025-11": 20, "2025-12": 30,
                  "2026-05": 40, "2026-07": 50, "2026-08": 60}
        result = calculate(history(values))
        self.assertEqual(result["method"], "extended_12")
        self.assertEqual(len(result["selected_periods"]), 6)
        self.assertAlmostEqual(sum(p["normalized_weight"] for p in result["selected_periods"]), 1)
        self.assertLess(result["confidence"]["score"], 0.8)
        self.assertIn("missing_recent_months", result["confidence"]["reasons"])

    def test_old_single_observation_is_low_confidence(self):
        result = calculate(history({"2024-01": 25}))
        self.assertEqual(result["method"], "historical_32")
        self.assertEqual(result["base_demand_monthly"], 25)
        self.assertEqual(result["confidence"]["level"], "low")

    def test_no_history_is_unknown_not_zero(self):
        result = calculate(history({}))
        self.assertIsNone(result["base_demand_monthly"])
        self.assertEqual(result["confidence"]["level"], "unavailable")

    def test_incomplete_september_is_excluded(self):
        values = {f"2026-{month:02d}": 10 for month in range(3, 9)}
        values["2026-09"] = 1000
        result = calculate(history(values))
        self.assertEqual(result["as_of_complete_month"], "2026-08")
        self.assertEqual(result["base_demand_monthly"], 10)
        self.assertNotIn("2026-09", [item["period"] for item in result["selected_periods"]])

    def test_adjusted_month_lowers_confidence_without_changing_trace(self):
        values = {f"2026-{month:02d}": 20 for month in range(3, 9)}
        clean = calculate(history(values))
        adjusted = calculate(history(values, {"2026-08": 100}))
        self.assertEqual(clean["base_demand_monthly"], adjusted["base_demand_monthly"])
        self.assertLess(adjusted["confidence"]["score"], clean["confidence"]["score"])
        self.assertIn("one_off_adjustment_in_selected_months", adjusted["confidence"]["reasons"])


if __name__ == "__main__":
    unittest.main()

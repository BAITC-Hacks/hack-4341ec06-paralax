"""Synthetic checks for separate trend and month-specific seasonality."""

import unittest

from base_demand import calculate
from clean_demand import MONTHS, SOURCE_COMMIT
from forecast_demand import forecast, seasonality_profile


def records(values: dict[str, float | None]) -> tuple[dict, dict]:
    periods = []
    for month in MONTHS:
        value = values.get(month)
        periods.append({
            "period": month, "clean_demand": value, "raw_sales": value,
            "excluded_one_off": 0, "estimated_lost_demand": 0,
            "stock": 10 if value is not None else None,
            "partial_period": month == "2026-09",
            "source_cells": {}, "reasons": [],
        })
    clean = {"brand": "IEK", "sku": "TEST_", "source_commit": SOURCE_COMMIT,
             "name": "Synthetic", "unit": "шт", "periods": periods}
    return clean, calculate(clean)


class ForecastTests(unittest.TestCase):
    def test_sustained_growth_in_clean_demand_increases_future_forecast(self):
        values = {f"2025-{month:02d}": 10 + month for month in range(9, 13)}
        values.update({f"2026-{month:02d}": 10 + month + 12 for month in range(1, 9)})
        clean, base = records(values)
        result = forecast(clean, base)
        self.assertEqual(result["trend"]["status"], "applied")
        self.assertGreater(result["trend"]["slope_per_month"], 0)
        self.assertLessEqual(result["trend"]["slope_per_month"], 0.05 * base["base_demand_monthly"])
        self.assertGreater(result["forecast_months"][-1]["final_forecast"],
                           result["forecast_months"][0]["final_forecast"])
        self.assertEqual(result["seasonality"]["status"], "neutral_insufficient_history")

    def test_single_spike_does_not_become_sustained_trend(self):
        values = {f"2025-{month:02d}": 10 for month in range(9, 13)}
        values.update({f"2026-{month:02d}": 10 for month in range(1, 9)})
        values["2026-08"] = 1000
        clean, base = records(values)
        result = forecast(clean, base)
        self.assertEqual(result["trend"]["status"], "neutral")
        self.assertEqual(result["trend"]["slope_per_month"], 0)

    def test_sku_seasonality_applies_to_specific_future_month(self):
        values = {f"{year}-{month:02d}": 30 if month == 1 else 10
                  for year in (2024, 2025) for month in range(1, 13)}
        values.update({f"2026-{month:02d}": 30 if month == 1 else 10
                       for month in range(1, 9)})
        clean, base = records(values)
        result = forecast(clean, base)
        self.assertEqual(result["seasonality"]["status"], "sku_history")
        self.assertEqual(result["trend"]["status"], "neutral")
        future = {p["month"]: p for p in result["forecast_months"]}
        self.assertGreater(future["2027-01"]["final_forecast"],
                           future["2026-10"]["final_forecast"])
        self.assertGreater(future["2027-01"]["seasonality_adjustment"], 0)

    def test_sparse_years_keep_seasonality_neutral(self):
        values = {f"2024-{month:02d}": 30 if month == 1 else 10
                  for month in range(1, 13)}
        values.update({f"2025-{month:02d}": 30 if month == 1 else 10
                       for month in range(1, 9)})
        clean, base = records(values)
        result = forecast(clean, base)
        self.assertEqual(seasonality_profile(clean)["status"], "neutral_insufficient_history")
        self.assertTrue(all(p["seasonality_multiplier"] == 1 for p in result["forecast_months"]
                            if p["final_forecast"] is not None))

    def test_sustained_decline_reduces_future_forecast(self):
        values = {f"2025-{month:02d}": 40 - (month - 9) * 2 for month in range(9, 13)}
        values.update({f"2026-{month:02d}": 32 - month * 2 for month in range(1, 9)})
        clean, base = records(values)
        result = forecast(clean, base)
        self.assertEqual(result["trend"]["status"], "applied")
        self.assertLess(result["trend"]["slope_per_month"], 0)
        self.assertGreaterEqual(result["trend"]["slope_per_month"], -0.05 * base["base_demand_monthly"])
        self.assertLess(result["forecast_months"][-1]["final_forecast"],
                        result["forecast_months"][0]["final_forecast"])

    def test_no_base_demand_produces_unknown_forecast(self):
        clean, base = records({})
        result = forecast(clean, base)
        self.assertTrue(all(item["final_forecast"] is None for item in result["forecast_months"]))
        self.assertTrue(all(item["reason"] == "base_demand_unavailable"
                            for item in result["forecast_months"]))

    def test_components_add_up_and_current_partial_month_is_labeled(self):
        values = {f"2026-{month:02d}": 20 for month in range(3, 9)}
        clean, base = records(values)
        result = forecast(clean, base)
        self.assertEqual(result["forecast_months"][0]["month"], "2026-09")
        self.assertEqual(result["forecast_months"][0]["month_kind"], "current_partial_month")
        for item in result["forecast_months"]:
            self.assertAlmostEqual(item["base_demand"] + item["trend_adjustment"]
                                   + item["seasonality_adjustment"],
                                   item["final_forecast"])


if __name__ == "__main__":
    unittest.main()

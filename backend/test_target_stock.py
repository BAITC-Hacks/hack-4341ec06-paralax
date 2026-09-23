"""Synthetic checks for Stage 4 lead-time demand and target stock."""

import unittest

from target_stock import calculate_target_stock


def forecast_record(monthly_values: dict[str, float | None]) -> dict:
    """Build the relevant part of a Stage 3 result without partner data."""
    return {
        "source_commit": "synthetic",
        "brand": "IEK",
        "sku": "TEST_",
        "name": "Synthetic item",
        "unit": "шт",
        "as_of_complete_month": "2026-08",
        "forecast_months": [
            {"month": month, "final_forecast": value}
            for month, value in monthly_values.items()
        ],
    }


class TargetStockTests(unittest.TestCase):
    def test_partial_months_contribute_only_covered_days(self):
        # [2026-09-23, 2026-10-23) covers 8 September and 22 October days.
        result = calculate_target_stock(
            forecast_record({"2026-09": 30.0, "2026-10": 62.0}),
            planning_date="2026-09-23",
            lead_time_days=30,
            safety_stock_days=7,
            upstream_sha256="abc",
        )

        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["upstream_sha256"], "abc")
        self.assertEqual(
            [(row["month"], row["covered_days"], row["days_in_month"])
             for row in result["forecast_months_in_lead_time"]],
            [("2026-09", 8, 30), ("2026-10", 22, 31)],
        )
        september, october = result["forecast_months_in_lead_time"]
        self.assertEqual(september["monthly_forecast"], 30.0)
        self.assertEqual(october["monthly_forecast"], 62.0)
        self.assertAlmostEqual(september["demand_contribution"], 8.0)
        self.assertAlmostEqual(october["demand_contribution"], 44.0)
        self.assertAlmostEqual(result["lead_time_demand"], 52.0)
        self.assertAlmostEqual(result["safety_stock"], 52.0 / 30 * 7)
        self.assertAlmostEqual(result["target_stock"], 52.0 + 52.0 / 30 * 7)

    def test_full_month_at_boundary_is_counted_once(self):
        result = calculate_target_stock(
            forecast_record({"2026-10": 93.0}),
            planning_date="2026-10-01",
            lead_time_days=31,
            safety_stock_days=0,
            upstream_sha256="abc",
        )

        self.assertEqual(len(result["forecast_months_in_lead_time"]), 1)
        self.assertEqual(result["forecast_months_in_lead_time"][0]["covered_days"], 31)
        self.assertEqual(result["lead_time_demand"], 93.0)
        self.assertEqual(result["safety_stock"], 0.0)
        self.assertEqual(result["target_stock"], 93.0)

    def test_leap_day_and_next_month_use_their_actual_lengths(self):
        result = calculate_target_stock(
            forecast_record({"2028-02": 29.0, "2028-03": 31.0}),
            planning_date="2028-02-28",
            lead_time_days=3,
            safety_stock_days=1,
            upstream_sha256="abc",
        )

        self.assertEqual(
            [(row["covered_days"], row["days_in_month"], row["demand_contribution"])
             for row in result["forecast_months_in_lead_time"]],
            [(2, 29, 2.0), (1, 31, 1.0)],
        )
        self.assertEqual(result["lead_time_demand"], 3.0)
        self.assertEqual(result["safety_stock"], 1.0)
        self.assertEqual(result["target_stock"], 4.0)

    def test_zero_and_fractional_forecasts_are_not_rounded(self):
        zero = calculate_target_stock(
            forecast_record({"2026-10": 0.0}),
            planning_date="2026-10-10",
            lead_time_days=5,
            safety_stock_days=2,
            upstream_sha256="abc",
        )
        self.assertEqual(zero["status"], "calculated")
        self.assertEqual(zero["target_stock"], 0.0)

        fractional = calculate_target_stock(
            forecast_record({"2026-10": 15.5}),
            planning_date="2026-10-10",
            lead_time_days=5,
            safety_stock_days=2,
            upstream_sha256="abc",
        )
        self.assertAlmostEqual(fractional["lead_time_demand"], 2.5)
        self.assertAlmostEqual(fractional["safety_stock"], 1.0)
        self.assertAlmostEqual(fractional["target_stock"], 3.5)

    def test_unknown_forecast_remains_unknown_not_zero(self):
        result = calculate_target_stock(
            forecast_record({"2026-09": 30.0, "2026-10": None}),
            planning_date="2026-09-23",
            lead_time_days=30,
            safety_stock_days=7,
            upstream_sha256="abc",
        )

        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["forecast_months_in_lead_time"][1]["demand_contribution"])
        self.assertIsNone(result["lead_time_demand"])
        self.assertIsNone(result["safety_stock"])
        self.assertIsNone(result["target_stock"])

    def test_missing_covered_month_is_an_error_not_a_shorter_horizon(self):
        with self.assertRaises(ValueError):
            calculate_target_stock(
                forecast_record({"2026-09": 30.0}),
                planning_date="2026-09-23",
                lead_time_days=30,
                safety_stock_days=7,
                upstream_sha256="abc",
            )

    def test_invalid_parameters_are_rejected(self):
        record = forecast_record({"2026-09": 30.0})
        for lead_time in (0, -1, 2.5):
            with self.subTest(lead_time_days=lead_time), self.assertRaises(ValueError):
                calculate_target_stock(record, planning_date="2026-09-23",
                                       lead_time_days=lead_time, safety_stock_days=7,
                                       upstream_sha256="abc")
        with self.assertRaises(ValueError):
            calculate_target_stock(record, planning_date="2026-09-23",
                                   lead_time_days=5, safety_stock_days=-1,
                                   upstream_sha256="abc")
        with self.assertRaises(ValueError):
            calculate_target_stock(record, planning_date="2026-09-31",
                                   lead_time_days=5, safety_stock_days=7,
                                   upstream_sha256="abc")


if __name__ == "__main__":
    unittest.main()

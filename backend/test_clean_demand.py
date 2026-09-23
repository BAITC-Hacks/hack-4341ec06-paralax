"""Synthetic acceptance checks; no partner data is committed with tests."""

import unittest

from clean_demand import clean_product


def product(months: dict, docs: list | None = None) -> dict:
    return {
        "brand": "IEK", "sku": "TEST_", "unit": "шт", "name": "Synthetic",
        "docs": docs or [], "months": months,
    }


def month(sales: float | None, stock: float | None) -> dict:
    return {
        "sales": {"value": sales, "ref": {"row": 1, "column": 2}},
        "stock": {"value": stock, "ref": {"row": 1, "column": 3}},
    }


class CleanDemandTests(unittest.TestCase):
    def test_single_large_document_does_not_drive_regular_demand(self):
        docs = [{"month": "2025-01", "row": i + 2, "document": str(i),
                 "quantity": 10.0, "unit": "шт"} for i in range(9)]
        docs.append({"month": "2025-01", "row": 11, "document": "large",
                     "quantity": 1000.0, "unit": "шт"})
        result = clean_product(product({"2025-01": month(1090, 100)}, docs))
        jan = next(p for p in result["periods"] if p["period"] == "2025-01")
        self.assertEqual(jan["raw_sales"], 1090)
        self.assertEqual(jan["excluded_one_off"], 990)
        self.assertEqual(jan["clean_demand"], 100)
        self.assertEqual(jan["outlier_documents"][0]["row"], 11)
        self.assertEqual(len(result["document_movements"]), 10)

    def test_unreconciled_document_does_not_reduce_monthly_sales(self):
        docs = [{"month": "2025-01", "row": i + 2, "document": str(i),
                 "quantity": 10.0, "unit": "шт"} for i in range(9)]
        docs.append({"month": "2025-01", "row": 11, "document": "large",
                     "quantity": 1000.0, "unit": "шт"})
        jan = next(p for p in clean_product(product({"2025-01": month(20, 100)}, docs))["periods"]
                   if p["period"] == "2025-01")
        self.assertEqual(jan["excluded_one_off"], 0)
        self.assertEqual(jan["clean_demand"], 20)
        self.assertIn("one_off_document_unreconciled_no_exclusion", jan["reasons"])

    def test_zero_stock_and_zero_sales_estimates_possible_lost_demand(self):
        result = clean_product(product({
            "2025-01": month(20, 50), "2025-02": month(0, 0),
            "2025-03": month(20, 50),
        }))
        feb = next(p for p in result["periods"] if p["period"] == "2025-02")
        self.assertEqual(feb["estimated_lost_demand"], 20)
        self.assertEqual(feb["clean_demand"], 20)
        self.assertIn("possible_stockout_beginning_stock_zero", feb["reasons"])
        self.assertEqual(feb["reference_periods"], ["2025-01", "2025-03"])

    def test_sku_month_seasonality_changes_stockout_estimate(self):
        months = {f"{year}-{m:02d}": month(30 if m == 1 else 10, 50)
                  for year in (2024, 2025) for m in range(1, 13)}
        months["2026-01"] = month(0, 0)
        january = next(p for p in clean_product(product(months))["periods"]
                       if p["period"] == "2026-01")
        self.assertEqual(january["seasonality_multiplier"], 1.5)
        self.assertEqual(january["estimated_lost_demand"], 15)
        self.assertIn("sku_calendar_month_seasonality", january["reasons"])

    def test_missing_stock_and_partial_month_are_not_imputed(self):
        result = clean_product(product({
            "2026-07": month(20, 50), "2026-08": month(0, None),
            "2026-09": month(0, 0),
        }))
        aug = next(p for p in result["periods"] if p["period"] == "2026-08")
        sep = next(p for p in result["periods"] if p["period"] == "2026-09")
        self.assertEqual(aug["estimated_lost_demand"], 0)
        self.assertEqual(sep["estimated_lost_demand"], 0)
        self.assertIn("partial_period", sep["reasons"])

    def test_negative_net_returns_remain_visible(self):
        result = clean_product(product({"2025-04": month(-5, 10)}))
        april = next(p for p in result["periods"] if p["period"] == "2025-04")
        self.assertEqual(april["raw_sales"], -5)
        self.assertEqual(april["clean_demand"], 0)
        self.assertIn("negative_net_sales_return", april["reasons"])


if __name__ == "__main__":
    unittest.main()

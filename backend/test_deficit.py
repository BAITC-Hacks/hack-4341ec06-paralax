"""Synthetic checks for Stage 5 deficit, without partner workbook data."""

import io
import json
import math
import unittest

from deficit import calculate_deficit, load_balances


def target_record(target_stock: float | None = 334.0,
                  status: str = "calculated") -> dict:
    return {
        "brand": "IEK",
        "sku": "TEST_",
        "target_stock": target_stock,
        "status": status,
        "planning_date": "2026-09-23",
        "source_commit": "synthetic",
    }


def quantity_record(quantity: float | None,
                    quality: str = "confirmed_current",
                    as_of_date: str | None = "2026-09-23") -> dict:
    return {
        "quantity": quantity,
        "quality": quality,
        "as_of_date": as_of_date,
        "source_refs": [{"source": "synthetic", "field": "quantity"}],
    }


def balance_record(stock: float | None = 74.0,
                   transit: float | None = 100.0) -> dict:
    return {
        "brand": "IEK",
        "sku": "TEST_",
        "current_stock": quantity_record(stock),
        "goods_in_transit": quantity_record(transit),
    }


def calculate(target: dict | None = None, balance: dict | None = None) -> dict:
    return calculate_deficit(
        target if target is not None else target_record(),
        balance if balance is not None else balance_record(),
        target_sha256="abc",
        balance_sha256="def",
    )


class DeficitTests(unittest.TestCase):
    def test_subtracts_stock_and_transit_with_traceable_inputs(self):
        result = calculate()

        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["raw_deficit"], 160.0)
        self.assertEqual(result["deficit"], 160.0)
        self.assertEqual(result["target_sha256"], "abc")
        self.assertEqual(result["balance_sha256"], "def")
        self.assertEqual(result["unavailable_reasons"], [])
        self.assertEqual(result["provisional_reasons"], [])

    def test_overcoverage_keeps_signed_gap_but_zeroes_need(self):
        result = calculate(target_record(50.0), balance_record(74.0, 100.0))

        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["raw_deficit"], -124.0)
        self.assertEqual(result["deficit"], 0.0)

    def test_more_stock_or_more_transit_cannot_increase_deficit(self):
        original = calculate(target_record(200.0), balance_record(50.0, 20.0))
        with_more_stock = calculate(target_record(200.0), balance_record(65.0, 20.0))
        with_more_transit = calculate(target_record(200.0), balance_record(50.0, 35.0))

        self.assertEqual(original["deficit"], 130.0)
        self.assertEqual(with_more_stock["deficit"], 115.0)
        self.assertEqual(with_more_transit["deficit"], 115.0)

    def test_fractional_deficit_is_not_rounded_at_this_stage(self):
        result = calculate(target_record(19.25), balance_record(3.5, 1.125))

        self.assertAlmostEqual(result["raw_deficit"], 14.625)
        self.assertAlmostEqual(result["deficit"], 14.625)

    def test_unknown_target_remains_unavailable_but_numeric_zero_is_known(self):
        unknown = calculate(target_record(None, "unavailable"), balance_record(0, 0))
        known_zero = calculate(target_record(0.0), balance_record(0, 0))

        self.assertEqual(unknown["status"], "unavailable")
        self.assertIsNone(unknown["raw_deficit"])
        self.assertIsNone(unknown["deficit"])
        self.assertTrue(unknown["unavailable_reasons"])
        self.assertEqual(known_zero["status"], "calculated")
        self.assertEqual(known_zero["raw_deficit"], 0.0)
        self.assertEqual(known_zero["deficit"], 0.0)

    def test_missing_current_stock_does_not_use_historical_stock_as_current(self):
        balance = balance_record(None, 10.0)
        balance["current_stock"] = quantity_record(None, "missing", None)
        balance["historical_stock"] = quantity_record(57.0, "historical", "2026-09-01")

        result = calculate(target_record(100.0), balance)

        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["raw_deficit"])
        self.assertIsNone(result["deficit"])
        self.assertTrue(result["unavailable_reasons"])

    def test_numeric_historical_stock_is_explicitly_provisional(self):
        balance = balance_record(57.0, 10.0)
        balance["current_stock"] = quantity_record(57.0, "historical", "2026-09-01")

        result = calculate(target_record(100.0), balance)

        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["raw_deficit"], 33.0)
        self.assertEqual(result["deficit"], 33.0)
        self.assertTrue(result["provisional_reasons"])

    def test_ambiguous_transit_date_is_explicitly_provisional(self):
        balance = balance_record(74.0, 100.0)
        balance["goods_in_transit"] = quantity_record(100.0, "ambiguous_date", None)

        result = calculate(target_record(), balance)

        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["deficit"], 160.0)
        self.assertTrue(result["provisional_reasons"])

    def test_missing_transit_is_not_assumed_zero(self):
        balance = balance_record(74.0, None)
        balance["goods_in_transit"] = quantity_record(None, "missing", None)

        result = calculate(target_record(), balance)

        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["raw_deficit"])
        self.assertIsNone(result["deficit"])
        self.assertTrue(result["unavailable_reasons"])

    def test_negative_and_nonfinite_quantities_are_rejected(self):
        for invalid in (-1.0, math.nan, math.inf, -math.inf):
            with self.subTest(field="target_stock", value=invalid):
                with self.assertRaises(ValueError):
                    calculate(target_record(invalid), balance_record())
            with self.subTest(field="current_stock", value=invalid):
                with self.assertRaises(ValueError):
                    calculate(target_record(), balance_record(invalid, 0.0))
            with self.subTest(field="goods_in_transit", value=invalid):
                with self.assertRaises(ValueError):
                    calculate(target_record(), balance_record(0.0, invalid))

    def test_mismatched_brand_or_sku_is_rejected(self):
        for field, value in (("brand", "Systeme Electric"), ("sku", "OTHER_")):
            with self.subTest(field=field):
                balance = balance_record()
                balance[field] = value
                with self.assertRaises(ValueError):
                    calculate(target_record(), balance)

    def test_newer_balance_source_can_be_used_without_faking_stage1_lineage(self):
        balance = balance_record()
        balance["source_commit"] = "new-stock-snapshot"
        result = calculate(target_record(), balance)
        self.assertEqual(result["status"], "calculated")
        self.assertEqual(result["balance_source_commit"], "new-stock-snapshot")

    def test_user_override_retains_replaced_source_evidence(self):
        balance = balance_record()
        balance["source_current_stock"] = quantity_record(90, "ambiguous_date", None)
        balance["source_goods_in_transit"] = quantity_record(120, "ambiguous_date", None)

        result = calculate(target_record(), balance)

        self.assertEqual(result["source_current_stock"]["quantity"], 90)
        self.assertEqual(result["source_goods_in_transit"]["quantity"], 120)

    def test_old_date_is_provisional_even_if_labeled_confirmed(self):
        balance = balance_record()
        balance["current_stock"]["as_of_date"] = "2026-09-01"
        result = calculate(target_record(), balance)
        self.assertEqual(result["status"], "provisional")
        self.assertIn("current_stock:date_differs_from_planning_date",
                      result["provisional_reasons"])

    def test_confirmed_value_without_source_reference_is_provisional(self):
        balance = balance_record()
        balance["current_stock"]["source_refs"] = []
        result = calculate(target_record(), balance)
        self.assertEqual(result["status"], "provisional")
        self.assertIn("current_stock:source_ref_missing", result["provisional_reasons"])

    def test_balance_derived_from_different_stage1_is_rejected(self):
        target = target_record()
        target["stage1_sha256"] = "first"
        balance = balance_record()
        balance["stage1_sha256"] = "other"
        with self.assertRaises(ValueError):
            calculate(target, balance)

    def test_duplicate_balance_keys_are_rejected(self):
        row = json.dumps(balance_record()) + "\n"

        class RepeatedRows:
            def open(self, **_kwargs):
                return io.StringIO(row + row)

        with self.assertRaises(ValueError):
            load_balances(RepeatedRows())


if __name__ == "__main__":
    unittest.main()

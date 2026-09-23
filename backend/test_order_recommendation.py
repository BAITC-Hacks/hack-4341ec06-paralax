"""Synthetic checks for Stage 6, including the Stage-5 arithmetic boundary."""

import io
import json
import math
import unittest

from deficit import calculate_deficit
from order_recommendation import calculate_order, load_jsonl, rounded_order


def target_record(target: float | None = 200.0, lead_demand: float | None = 160.0) -> dict:
    return {
        "source_commit": "synthetic", "brand": "Systeme Electric", "sku": "TEST_",
        "planning_date": "2026-09-23", "target_stock": target,
        "lead_time_demand": lead_demand, "status": "calculated" if target is not None else "unavailable",
    }


def balance_value(quantity: float | None, quality: str = "confirmed_current") -> dict:
    return {
        "quantity": quantity, "quality": quality, "as_of_date": "2026-09-23",
        "source_refs": [{"source": "synthetic-user-input"}],
    }


def deficit_record(target: dict, stock: float | None, transit: float | None,
                   quality: str = "confirmed_current") -> dict:
    balance = {
        "brand": target["brand"], "sku": target["sku"],
        "current_stock": balance_value(stock, quality),
        "goods_in_transit": balance_value(transit),
    }
    return calculate_deficit(target, balance, target_sha256="target-hash",
                             balance_sha256="balance-hash")


def rule(kind: str = "multiple", quantity: int = 20, status: str = "valid") -> dict:
    return {
        "source_commit": "synthetic", "brand": "Systeme Electric", "sku": "TEST_",
        "rule_kind": kind, "quantity": quantity, "status": status,
        "source_refs": [{"source": "synthetic-rule"}], "notes": [],
    }


def order(target: dict, stock: float | None, transit: float | None,
          packing: dict | None = None, quality: str = "confirmed_current") -> dict:
    deficit = deficit_record(target, stock, transit, quality)
    return calculate_order(deficit, target, packing if packing is not None else rule())


class OrderRecommendationTests(unittest.TestCase):
    def test_163_deficit_multiple_20_gives_180(self):
        result = order(target_record(334, 300), 71, 100)

        self.assertEqual(result["raw_deficit"], 163)
        self.assertTrue(result["purchase_needed"])
        self.assertEqual(result["recommended_order"], 180)
        self.assertEqual(result["urgency"], "HIGH")
        self.assertEqual(result["status"], "calculated")

    def test_binary_float_noise_does_not_buy_an_extra_pack(self):
        self.assertEqual(rounded_order(20.000000000000004, "multiple", 20), 20)
        self.assertEqual(rounded_order(20.0000001, "multiple", 20), 40)

    def test_minimum_dispatch_is_not_a_multiple(self):
        target = target_record(12, 10)
        target["brand"] = "IEK"
        packing = rule("minimum_dispatch", 10)
        packing["brand"] = "IEK"
        small = order(target, 11, 0, packing)
        larger = order(target_record(25, 20) | {"brand": "IEK"}, 11, 0, packing)

        self.assertEqual(small["recommended_order"], 10)
        self.assertEqual(larger["recommended_order"], 14)
        self.assertEqual(small["status"], "provisional")
        self.assertIn("minimum_dispatch_interpretation_unconfirmed", small["reasons"])

    def test_zero_need_never_creates_minimum_order_and_does_not_require_rule(self):
        target = target_record(50, 40)
        deficit = deficit_record(target, 40, 20)
        result = calculate_order(deficit, target, None)

        self.assertEqual(result["raw_deficit"], -10)
        self.assertFalse(result["purchase_needed"])
        self.assertEqual(result["recommended_order"], 0)
        self.assertEqual(result["urgency"], "LOW")
        self.assertEqual(result["status"], "calculated")
        invalid_rule = rule("multiple", 0, status="invalid")
        also_zero = calculate_order(deficit, target, invalid_rule)
        self.assertEqual(also_zero["recommended_order"], 0)

    def test_unknown_stock_or_transit_is_not_zero(self):
        for stock, transit in ((None, 0), (0, None)):
            with self.subTest(stock=stock, transit=transit):
                result = order(target_record(), stock, transit)
                self.assertIsNone(result["purchase_needed"])
                self.assertIsNone(result["recommended_order"])
                self.assertIsNone(result["urgency"])
                self.assertEqual(result["status"], "unavailable")

    def test_positive_need_without_rule_is_known_but_order_unknown(self):
        target = target_record(100, 80)
        result = calculate_order(deficit_record(target, 60, 0), target, None)

        self.assertTrue(result["purchase_needed"])
        self.assertIsNone(result["recommended_order"])
        self.assertEqual(result["urgency"], "HIGH")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("packing_rule_missing", result["reasons"])

    def test_urgency_distinguishes_lead_time_risk_from_safety_shortfall(self):
        target = target_record(100, 80)
        high = order(target, 70, 0)
        medium = order(target, 85, 0)
        low = order(target, 100, 0)

        self.assertEqual([high["urgency"], medium["urgency"], low["urgency"]],
                         ["HIGH", "MEDIUM", "LOW"])
        self.assertIn("current_stock_below_lead_time_demand", high["urgency_reasons"])
        self.assertIn("lead_time_covered_but_safety_target_short", medium["urgency_reasons"])

    def test_more_stock_or_transit_does_not_increase_order(self):
        target = target_record(200, 160)
        original = order(target, 50, 20)
        more_stock = order(target, 70, 20)
        more_transit = order(target, 50, 40)

        self.assertLessEqual(more_stock["recommended_order"], original["recommended_order"])
        self.assertLessEqual(more_transit["recommended_order"], original["recommended_order"])

    def test_provisional_balance_does_not_answer_purchase_question(self):
        result = order(target_record(100, 80), 10, 0, quality="ambiguous_date")
        self.assertEqual(result["raw_deficit"], 90)
        self.assertIsNone(result["purchase_needed"])
        self.assertIsNone(result["recommended_order"])
        self.assertIsNone(result["urgency"])
        self.assertEqual(result["status"], "provisional")
        self.assertIn("current_stock:ambiguous_date", result["reasons"])

    def test_zero_order_can_still_have_high_arrival_timing_risk(self):
        result = order(target_record(100, 80), 3, 120)

        self.assertFalse(result["purchase_needed"])
        self.assertEqual(result["recommended_order"], 0)
        self.assertEqual(result["urgency"], "HIGH")
        self.assertIn("incoming_arrival_timing_unverified", result["urgency_reasons"])

    def test_invalid_rules_and_stale_arithmetic_fail_closed(self):
        for value in (0, -1, 2.5, math.nan, math.inf, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    rounded_order(5, "multiple", value)
        target = target_record(100, 80)
        deficit = deficit_record(target, 20, 0)
        deficit["raw_deficit"] = 999
        with self.assertRaises(ValueError):
            calculate_order(deficit, target, rule())
        no_refs = rule()
        no_refs["source_refs"] = []
        with self.assertRaises(ValueError):
            calculate_order(deficit_record(target, 20, 0), target, no_refs)

    def test_duplicate_rule_keys_are_rejected(self):
        row = json.dumps(rule()) + "\n"

        class RepeatedRows:
            def open(self, **_kwargs):
                return io.StringIO(row + row)

        with self.assertRaises(ValueError):
            load_jsonl(RepeatedRows(), "packing-rule")


if __name__ == "__main__":
    unittest.main()

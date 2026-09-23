"""Synthetic checks for supplier order-rule extraction and source evidence."""

from __future__ import annotations

import unittest

from extract_packing_rules import parse_rule_rows, positive_integer, source_value


def iek_row(sku: object, rule: object) -> list[object]:
    return [1, sku, "article", "name", rule]


def systeme_row(sku: object, rule: object) -> list[object]:
    return [1, "name", sku, "article", rule]


class ExtractPackingRulesTests(unittest.TestCase):
    def test_only_explicit_positive_integer_excel_numbers_are_valid(self) -> None:
        self.assertEqual(positive_integer(6), 6)
        self.assertEqual(positive_integer(6.0), 6)
        for value in (None, True, "6", "#N/A", 0, -1, 1.5, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(positive_integer(value))
        self.assertEqual(source_value(float("inf")), "inf")

    def test_iek_minimum_dispatch_preserves_duplicate_cell_refs(self) -> None:
        parsed = parse_rule_rows("IEK", [
            (427, iek_row("270400035_", 6)),
            (1875, iek_row("270400035_", 6)),
        ])
        item = parsed["270400035_"]
        self.assertEqual(item["rule_kind"], "minimum_dispatch")
        self.assertEqual(item["quantity"], 6)
        self.assertEqual(item["status"], "valid")
        self.assertEqual([ref["cell"] for ref in item["source_refs"]], ["E427", "E1875"])
        self.assertIn("duplicate_identical_rule", item["notes"])

    def test_conflicting_duplicate_does_not_choose_a_rule(self) -> None:
        parsed = parse_rule_rows("IEK", [
            (20, iek_row("sku-a", 6)),
            (30, iek_row("sku-a", 12)),
        ])
        item = parsed["sku-a"]
        self.assertEqual(item["status"], "conflict")
        self.assertIsNone(item["quantity"])
        self.assertEqual(len(item["source_refs"]), 2)

    def test_systeme_multiple_and_unusable_rules_are_distinct(self) -> None:
        parsed = parse_rule_rows("Systeme Electric", [
            (3, systeme_row(" 030200128_ ", 5.0)),
            (4, systeme_row("bad", "#N/A")),
            (5, systeme_row("blank", None)),
            (6, systeme_row("fraction", 2.5)),
            (7, systeme_row(None, 99)),
        ])
        self.assertEqual(set(parsed), {"030200128_", "bad", "blank", "fraction"})
        self.assertEqual(parsed["030200128_"]["rule_kind"], "multiple")
        self.assertEqual(parsed["030200128_"]["quantity"], 5)
        self.assertEqual(parsed["030200128_"]["source_refs"][0]["cell"], "E3")
        self.assertEqual(parsed["bad"]["status"], "invalid")
        self.assertEqual(parsed["bad"]["source_refs"][0]["source_value"], "#N/A")
        self.assertEqual(parsed["blank"]["status"], "missing")
        self.assertEqual(parsed["fraction"]["status"], "invalid")


if __name__ == "__main__":
    unittest.main()

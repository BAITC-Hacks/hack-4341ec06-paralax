"""Synthetic checks for Stage-5 balance extraction and missing-value semantics."""

from __future__ import annotations

import unittest

from clean_demand import SOURCE_COMMIT
from extract_balances import (
    build_record,
    parse_iek_transit_rows,
    parse_systeme_rows,
)


IEK_HEADER = [
    "Код 1с", "Артикул", "Наименование",
    "УТ-1 (поступление до 30.09.2026)",
    "УТ-2 (поступление до 01.10.2026)",
    "УТ-3 (поступление до 02.10.2026)",
    "УТ-4 (поступление до 03.10.2026)",
    "УТ-5 (поступление до 04.10.2026)",
    "УТ-6 (поступление до 05.10.2026)",
]


def iek_row(sku: str, *shipments: object) -> list[object]:
    return [sku, "article", "name", *shipments, *([None] * (6 - len(shipments)))]


def systeme_row(sku: str, stock: object, transit: object,
                warehouses: tuple[object, object, object, object] = (0, 0, 0, 0)) -> list[object]:
    row: list[object] = [None] * 55
    row[2] = sku
    row[45:49] = warehouses
    row[49] = stock
    row[54] = transit
    return row


class ExtractBalancesTests(unittest.TestCase):
    def test_iek_combines_repeated_sku_rows_and_keeps_cell_evidence(self) -> None:
        parsed = parse_iek_transit_rows(IEK_HEADER, [
            (7, iek_row("sku-a", 2)),
            (8, iek_row("sku-a", None, 3)),
        ])
        item = parsed["sku-a"]
        self.assertEqual(item["evidence"]["quantity"], 5)
        self.assertEqual(item["evidence"]["quality"], "ambiguous_date")
        self.assertEqual(item["evidence"]["as_of_date"], "2026-09-22")
        self.assertEqual(len(item["evidence"]["source_refs"]), 12)
        self.assertEqual(item["evidence"]["source_refs"][0]["cell"], "D7")
        self.assertEqual(item["evidence"]["source_refs"][0]["expected_arrival_latest"], "2026-09-30")
        self.assertIn("duplicate_sku_rows_combined_by_shipment_cells", item["notes"])

    def test_iek_blank_is_unknown_but_explicit_zero_is_zero(self) -> None:
        parsed = parse_iek_transit_rows(IEK_HEADER, [
            (10, iek_row("blank")),
            (11, iek_row("zero", 0)),
        ])
        self.assertIsNone(parsed["blank"]["evidence"]["quantity"])
        self.assertEqual(parsed["blank"]["evidence"]["quality"], "missing")
        self.assertEqual(parsed["zero"]["evidence"]["quantity"], 0)
        self.assertEqual(parsed["zero"]["evidence"]["quality"], "ambiguous_date")

    def test_iek_invalid_cell_invalidates_sum(self) -> None:
        parsed = parse_iek_transit_rows(IEK_HEADER, [
            (12, iek_row("negative", 3, -1)),
            (13, iek_row("text", "5")),
        ])
        for sku in ("negative", "text"):
            self.assertIsNone(parsed[sku]["evidence"]["quantity"])
            self.assertEqual(parsed[sku]["evidence"]["quality"], "invalid_source")
            self.assertTrue(any(note.startswith("invalid_transit_cell:")
                                for note in parsed[sku]["notes"]))

    def test_systeme_uses_only_numeric_ax_bc_and_flags_scope_difference(self) -> None:
        parsed = parse_systeme_rows([
            (20, systeme_row("sku-a", 9, 0, (0, 0, 0, 2))),
            (21, systeme_row("sku-b", "9", None)),
        ])
        self.assertEqual(parsed["sku-a"]["current_stock"]["quantity"], 9)
        self.assertEqual(parsed["sku-a"]["goods_in_transit"]["quantity"], 0)
        self.assertIsNone(parsed["sku-a"]["current_stock"]["as_of_date"])
        self.assertEqual(parsed["sku-a"]["current_stock"]["source_refs"][0]["cell"], "AX20")
        self.assertEqual(parsed["sku-a"]["goods_in_transit"]["source_refs"][0]["cell"], "BC20")
        self.assertTrue(any(note.startswith("warehouse_scope_differs:")
                            for note in parsed["sku-a"]["notes"]))
        self.assertEqual(parsed["sku-b"]["current_stock"]["quality"], "invalid_source")
        self.assertEqual(parsed["sku-b"]["goods_in_transit"]["quality"], "missing")

    def test_iek_stage1_stock_is_historical_not_current(self) -> None:
        stage1 = {
            "source_commit": SOURCE_COMMIT, "brand": "IEK", "sku": "sku-a",
            "source_files": {"stock": {"file": "stock.xlsx", "sheet": "Лист_1"}},
            "periods": [{"period": "2026-09", "stock": 57.0,
                         "source_cells": {"stock": {"row": 368, "column": 36}}}],
        }
        result = build_record(stage1, "abc123", {}, {})
        self.assertIsNone(result["current_stock"]["quantity"])
        self.assertEqual(result["current_stock"]["quality"], "missing")
        self.assertEqual(result["historical_stock"]["quantity"], 57)
        self.assertEqual(result["historical_stock"]["as_of_date"], "2026-09-01")
        self.assertEqual(result["historical_stock"]["source_refs"][0]["cell"], "AJ368")
        self.assertIsNone(result["goods_in_transit"]["quantity"])
        self.assertEqual(result["goods_in_transit"]["source_refs"], [])


if __name__ == "__main__":
    unittest.main()

"""Synthetic lineage and arithmetic tests for the Stage-7 SKU trace."""

import json
import unittest
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from clean_demand import SOURCE_COMMIT
from deficit import calculate_deficit
from order_recommendation import calculate_order
from trace_sku import assemble_trace, load_selected, trace_stem


@contextmanager
def test_directory():
    path = Path(__file__).resolve().parent / f".test-trace-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        for child in path.iterdir():
            child.unlink()
        path.rmdir()


def fixture(stock: int | None = 4, stock_quality: str = "confirmed_current") -> tuple[dict, dict, dict, dict]:
    brand, sku = "Systeme Electric", "SYNTHETIC_"
    key = {"source_commit": SOURCE_COMMIT, "brand": brand, "sku": sku}
    hashes = {name: f"hash-{name}" for name in
              ("stage1", "stage2", "stage3", "stage4", "stage5", "stage6",
               "balances", "rules")}
    stage1 = {
        **key, "name": "Test part", "unit": "шт",
        "source_files": {
            "sales": {"file": "data/sales.xlsx", "sheet": "Sales"},
            "stock": {"file": "data/stock.xlsx", "sheet": "Stock"},
            "documents": {"file": "data/docs.xlsx", "sheet": "Docs"},
        },
        "document_movements": [{"month": "2026-08", "row": 42,
                                "document": "DOC-1", "quantity": 10, "unit": "шт"}],
        "outlier_rule": {"threshold": 8, "median": 3},
        "periods": [{
            "period": "2026-08", "raw_sales": 10, "observed_demand": 10,
            "excluded_one_off": 2, "adjusted_sales": 8,
            "document_reconciled": True,
            "estimated_lost_demand": 1, "clean_demand": 9,
            "source_cells": {"sales": {"row": 5, "column": 36},
                             "stock": {"row": 8, "column": 36}},
            "reasons": ["one_off_document_median_mad_iqr"],
            "outlier_documents": [{"row": 42, "document": "DOC-1",
                                   "quantity": 10, "excluded_excess": 2}],
        }],
    }
    stage2 = {
        **key, "upstream_sha256": hashes["stage1"],
        "base_demand_monthly": 9, "method": "synthetic",
        "selected_periods": [{"period": "2026-08", "clean_demand": 9,
                              "raw_weight": 1, "normalized_weight": 1,
                              "weighted_contribution": 9}],
        "window_periods": [], "confidence": {"level": "high", "score": 1},
    }
    stage3 = {
        **key, "stage1_sha256": hashes["stage1"],
        "stage2_sha256": hashes["stage2"], "base_demand_monthly": 9,
        "trend": {"status": "applied", "slope_per_month": 1, "evidence": []},
        "seasonality": {"status": "sku_history", "indices": {}, "evidence": {}},
        "forecast_months": [{"month": "2026-09", "base_demand": 9,
                             "trend_adjustment": 1, "seasonality_adjustment": 2,
                             "steps_from_base_month": 1,
                             "target_seasonality_index": 1.2,
                             "base_window_seasonality_index": 1,
                             "seasonality_multiplier": 1.2,
                             "final_forecast": 12}],
    }
    stage4 = {
        **key, "stage1_sha256": hashes["stage1"],
        "stage2_sha256": hashes["stage2"], "upstream_sha256": hashes["stage3"],
        "planning_date": "2026-09-01", "lead_time_days": 30,
        "safety_stock_days": 7.5, "average_daily_forecast": 0.4,
        "forecast_months_in_lead_time": [{"month": "2026-09", "covered_days": 30,
                                          "days_in_month": 30, "monthly_forecast": 12,
                                          "demand_contribution": 12}],
        "lead_time_demand": 12, "safety_stock": 3, "target_stock": 15,
        "status": "calculated",
    }
    balance = {
        "brand": brand, "sku": sku,
        "current_stock": {"quantity": stock, "quality": stock_quality,
                          "as_of_date": "2026-09-01",
                          "source_refs": [{"source": "synthetic-user-input"}]},
        "goods_in_transit": {"quantity": 1, "quality": "confirmed_current",
                             "as_of_date": "2026-09-01",
                             "source_refs": [{"source": "synthetic-user-input"}]},
    }
    stage5 = calculate_deficit(stage4, balance, hashes["stage4"], hashes["balances"])
    rule = {**key, "rule_kind": "multiple", "quantity": 6,
            "status": "valid", "source_refs": [{"cell": "E12"}], "notes": []}
    stage6 = calculate_order(stage5, stage4, rule,
                             deficit_sha256=hashes["stage5"],
                             rules_sha256=hashes["rules"])
    stages = {f"stage{i}": row for i, row in enumerate(
        (stage1, stage2, stage3, stage4, stage5, stage6), 1)}
    return stages, hashes, balance, rule


class TraceSkuTests(unittest.TestCase):
    def test_full_trace_keeps_all_stage_values_and_sources(self):
        stages, hashes, balance, rule = fixture()

        trace = assemble_trace(stages, hashes, balance, rule)

        self.assertTrue(trace["lineage"]["verified"])
        self.assertEqual(trace["stage1"]["periods"][0]["raw_sales"], 10)
        self.assertEqual(trace["stage2"]["base_demand_monthly"], 9)
        self.assertEqual(trace["stage3"]["forecast_months"][0]["final_forecast"], 12)
        self.assertEqual(trace["stage4"]["target_stock"], 15)
        self.assertEqual(trace["stage5"]["raw_deficit"], 10)
        self.assertEqual(trace["stage6"]["recommended_order"], 12)
        self.assertEqual(trace["stage1"]["periods"][0]["source_cells"]["sales"],
                         {"row": 5, "column": 36})

    def test_stale_stage_hash_or_changed_arithmetic_is_rejected(self):
        stages, hashes, balance, rule = fixture()
        stale = deepcopy(stages)
        stale["stage4"]["upstream_sha256"] = "other-forecast"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            assemble_trace(stale, hashes, balance, rule)

        changed = deepcopy(stages)
        changed["stage6"]["recommended_order"] = 18
        with self.assertRaisesRegex(ValueError, "recommended_order"):
            assemble_trace(changed, hashes, balance, rule)

    def test_unknown_and_provisional_stock_do_not_turn_into_a_purchase_answer(self):
        for stock, quality, expected_status in ((None, "missing", "unavailable"),
                                                (4, "ambiguous_date", "provisional")):
            with self.subTest(stock=stock, quality=quality):
                stages, hashes, balance, rule = fixture(stock, quality)
                trace = assemble_trace(stages, hashes, balance, rule)
                self.assertEqual(trace["stage6"]["status"], expected_status)
                self.assertIsNone(trace["stage6"]["purchase_needed"])
                self.assertIsNone(trace["stage6"]["recommended_order"])

    def test_changed_stock_quality_requires_recomputed_status(self):
        stages, hashes, balance, rule = fixture()
        balance["current_stock"]["quality"] = "ambiguous_date"
        with self.assertRaisesRegex(ValueError, "Stage-5 status"):
            assemble_trace(stages, hashes, balance, rule)

    def test_stage6_lead_time_evidence_cannot_differ_from_stage4(self):
        stages, hashes, balance, rule = fixture()
        stages["stage6"]["lead_time_demand"] = 999
        with self.assertRaisesRegex(ValueError, "Stage-6 lead_time_demand"):
            assemble_trace(stages, hashes, balance, rule)

    def test_missing_balance_source_is_not_verified(self):
        stages, hashes, _, rule = fixture()
        with self.assertRaisesRegex(ValueError, "Balance source lacks"):
            assemble_trace(stages, hashes, None, rule)

    def test_trace_filename_distinguishes_sanitized_skus(self):
        self.assertNotEqual(trace_stem("IEK", "A.B"), trace_stem("IEK", "A/B"))
        self.assertNotEqual(trace_stem("IEK", "A.B"), trace_stem("IEK", "A-B"))

    def test_duplicate_stage_records_are_rejected_while_brand_stays_in_key(self):
        with test_directory() as directory:
            path = directory / "rows.jsonl"
            row = {"brand": "IEK", "sku": "SAME_"}
            other_brand = {"brand": "Systeme Electric", "sku": "SAME_"}
            path.write_text("\n".join(json.dumps(item) for item in
                                       (row, other_brand)) + "\n", encoding="utf-8")
            selected, _ = load_selected(path, {("IEK", "SAME_"),
                                               ("Systeme Electric", "SAME_")}, "test")
            self.assertEqual(len(selected), 2)
            path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n",
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_selected(path, {("IEK", "SAME_")}, "test")


if __name__ == "__main__":
    unittest.main()

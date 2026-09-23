"""Synthetic rendering checks; no partner data is embedded in the test."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from trace_page import render_trace_html


class TracePageTests(unittest.TestCase):
    def test_full_chain_shows_numbers_sources_and_escapes_untrusted_text(self):
        dangerous = "<script>alert('x')</script>"
        trace = {
            "brand": "Synthetic", "sku": "TEST_", "name": dangerous,
            "unit": "шт", "source_commit": "test-commit", "planning_date": "2026-09-23",
            "lineage": {"stage1_sha256": "abc"},
            "stage1": {
                "source_files": {
                    "sales": {"file": "sales.xlsx", "sheet": "Лист_1"},
                    "stock": {"file": "stock.xlsx", "sheet": "Лист_1"},
                    "documents": {"file": "docs.xlsx", "sheet": "Лист_1"},
                },
                "periods": [{
                    "period": "2026-08", "raw_sales": 28, "document_month_total": 28,
                    "document_reconciled": True, "excluded_one_off": 5,
                    "adjusted_sales": 23, "stock": 0, "estimated_lost_demand": 2,
                    "clean_demand": 25, "reasons": ["one_off_document"],
                    "source_cells": {"sales": {"row": 7, "column": 8},
                                     "stock": {"row": 9, "column": 2}},
                    "outlier_documents": [{"row": 11, "document": dangerous,
                                           "quantity": 10, "excluded_excess": 5}],
                }],
                "document_movements": [{"month": "2026-08", "row": 11,
                                        "document": dangerous, "quantity": 10, "unit": "шт"}],
                "outlier_rule": {"threshold": 7},
            },
            "stage2": {
                "method": "recent_6", "base_demand_monthly": 25,
                "confidence": {"level": "high", "score": 0.9, "reasons": [], "factors": {}},
                "selected_periods": [{"period": "2026-08", "clean_demand": 25,
                                      "raw_sales": 28, "excluded_one_off": 5,
                                      "estimated_lost_demand": 2, "raw_weight": 1,
                                      "normalized_weight": 1, "weighted_contribution": 25,
                                      "source_cells": {"sales": {"row": 7, "column": 8}}}],
                "window_periods": [{"period": "2026-08", "clean_demand": 25,
                                    "selected": True, "reason": "valid"}],
            },
            "stage3": {
                "trend": {"status": "neutral", "reason": "insufficient_history",
                          "slope_per_month": 0, "evidence": []},
                "seasonality": {"status": "neutral_insufficient_history",
                                "indices": {}, "evidence": {}},
                "forecast_months": [{"month": "2026-09", "base_demand": 25,
                                     "steps_from_base_month": 1, "trend_adjustment": 0,
                                     "seasonality_multiplier": 1,
                                     "seasonality_adjustment": 0,
                                     "final_forecast": 25, "reason": "neutral_seasonality"}],
            },
            "stage4": {
                "planning_date": "2026-09-23", "lead_time_days": 30,
                "lead_time_source": "explicit", "horizon_end_exclusive": "2026-10-23",
                "forecast_months_in_lead_time": [{"month": "2026-09",
                                                  "covered_start": "2026-09-23",
                                                  "covered_end_exclusive": "2026-10-01",
                                                  "covered_days": 8, "days_in_month": 30,
                                                  "monthly_forecast": 25,
                                                  "daily_forecast": 25 / 30,
                                                  "demand_contribution": 20 / 3}],
                "lead_time_demand": 25, "safety_stock_days": 7,
                "average_daily_forecast": 25 / 30, "safety_stock": 35 / 6,
                "safety_stock_method": "synthetic", "target_stock": 30.833333333333332,
                "status": "calculated", "unavailable_reasons": [],
            },
            "stage5": {
                "planning_date": "2026-09-23", "status": "calculated",
                "target_stock": 30.833333333333332,
                "current_stock": {"quantity": 5, "quality": "confirmed_current",
                                  "as_of_date": "2026-09-23", "basis": "user_entered_attested",
                                  "source_refs": [{"source": "user_input", "note": dangerous}]},
                "goods_in_transit": {"quantity": 0, "quality": "confirmed_current",
                                     "as_of_date": "2026-09-23", "basis": "user_entered_attested",
                                     "source_refs": [{"source": "user_input"}]},
                "source_current_stock": {"quantity": None, "quality": "missing",
                                         "source_refs": [{"file": "old.xlsx", "sheet": "S",
                                                          "cell": "B4"}]},
                "raw_deficit": 25.833333333333332,
                "deficit": 25.833333333333332,
            },
            "stage6": {
                "purchase_needed": True, "packing_rule": {"rule_kind": "multiple",
                    "quantity": 20, "status": "valid",
                    "source_refs": [{"file": "moq.xlsx", "sheet": "S", "cell": "E2"}],
                    "notes": []},
                "raw_deficit": 25.833333333333332,
                "deficit": 25.833333333333332, "recommended_order": 40,
                "urgency": "HIGH", "lead_time_demand": 25,
                "current_stock": {"quantity": 5},
                "status": "calculated", "deficit_status": "calculated",
                "reasons": [], "urgency_reasons": ["current_stock_below_lead_time_demand"],
            },
        }
        output = Mock(spec=Path)
        render_trace_html(trace, output)
        page = output.write_text.call_args.args[0]
        output.write_text.assert_called_once_with(page, encoding="utf-8")
        self.assertIn("Как получен результат", page)
        self.assertIn("sales.xlsx · Лист_1 · H7", page)
        self.assertIn("docs.xlsx · Лист_1 · H11", page)
        self.assertIn("moq.xlsx · S · E2", page)
        self.assertIn("Введено и подтверждено пользователем", page)
        self.assertIn("25.833333333333332", page)
        self.assertIn("Заказать</span><b>40", page)
        self.assertIn("<h2>1. Продажи", page)
        self.assertIn("<h2>6. Нужно ли закупать", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn(dangerous, page)


if __name__ == "__main__":
    unittest.main()

"""Synthetic tests for explicit user balance input and its Stage-5 handoff."""

import json
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from apply_stock_inputs import apply_overrides, apply_stock_inputs, parse_entries
from deficit import calculate_deficit


@contextmanager
def test_directory():
    """Create a writable local fixture directory on Windows and Linux."""
    path = Path(__file__).resolve().parent / f".test-stock-inputs-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        for child in path.iterdir():
            child.unlink()
        path.rmdir()


def evidence(quantity, quality="missing", as_of_date=None):
    return {
        "quantity": quantity,
        "quality": quality,
        "as_of_date": as_of_date,
        "basis": "source_snapshot",
        "source_refs": [{"source": "synthetic workbook"}] if quantity is not None else [],
        "scope_note": "Synthetic source evidence",
    }


def balance(brand="IEK", sku="S1", stock=None, transit=None):
    return {
        "source_commit": "synthetic",
        "stage1_sha256": "same",
        "brand": brand,
        "sku": sku,
        "current_stock": evidence(stock, "ambiguous_date" if stock is not None else "missing"),
        "goods_in_transit": evidence(
            transit, "ambiguous_date" if transit is not None else "missing"),
        "historical_stock": evidence(44, "historical", "2026-09-01"),
        "notes": ["original_note"],
    }


def target(brand="IEK", sku="S1"):
    return {
        "source_commit": "synthetic",
        "stage1_sha256": "same",
        "brand": brand,
        "sku": sku,
        "target_stock": 30.0,
        "status": "calculated",
        "planning_date": "2026-09-23",
    }


class UserInputTests(unittest.TestCase):
    def test_parses_exact_keys_and_zero(self):
        parsed = parse_entries(["IEK:S1=0", "Systeme Electric:300200851_=3.5"],
                               "current_stock")
        self.assertEqual(parsed, {("IEK", "S1"): 0,
                                  ("Systeme Electric", "300200851_"): 3.5})

    def test_rejects_duplicate_invalid_or_missing_quantities(self):
        for entries in (
            ["IEK:S1=1", "IEK:S1=2"],
            ["IEK:S1=-1"], ["IEK:S1=NaN"], ["IEK:S1=Infinity"],
            ["IEK:S1=null"], ["IEK:S1=true"], ["IEK:S1=9007199254740992"],
            ["IEK:S1=1,5"], ["OTHER:S1=1"], ["IEK:=1"],
        ):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                parse_entries(entries, "current_stock")

    def test_stock_only_preserves_unknown_transit_and_source_evidence(self):
        original = balance(transit=None)
        with test_directory() as directory:
            source_path = directory / "source.jsonl"
            output_path = directory / "scenario.jsonl"
            source_path.write_text(json.dumps(original) + "\n", encoding="utf-8")

            counts = apply_stock_inputs(source_path, output_path, "2026-09-23",
                                        {("IEK", "S1"): 7}, {})

            scenario = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(counts, {"rows": 1, "stock_entries": 1, "transit_entries": 0})
            self.assertEqual(json.loads(source_path.read_text(encoding="utf-8")), original)
            self.assertEqual(scenario["source_current_stock"], original["current_stock"])
            self.assertEqual(scenario["goods_in_transit"], original["goods_in_transit"])
            self.assertEqual(scenario["historical_stock"], original["historical_stock"])
            self.assertEqual(scenario["current_stock"]["quantity"], 7)
            self.assertEqual(scenario["current_stock"]["basis"], "user_entered_attested")
            self.assertIn("не сверены автоматически", scenario["current_stock"]["scope_note"])
            deficit = calculate_deficit(target(), scenario)
            self.assertEqual(deficit["status"], "unavailable")
            self.assertIsNone(deficit["deficit"])

    def test_user_stock_and_transit_produce_traceable_answer(self):
        original = balance(transit=9)
        with test_directory() as directory:
            source_path = directory / "source.jsonl"
            output_path = directory / "scenario.jsonl"
            source_path.write_text(json.dumps(original) + "\n", encoding="utf-8")

            apply_stock_inputs(source_path, output_path, "2026-09-23",
                               {("IEK", "S1"): 7}, {("IEK", "S1"): 5})

            scenario = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(scenario["source_goods_in_transit"], original["goods_in_transit"])
            self.assertEqual(scenario["goods_in_transit"]["verification"],
                             "user_attested_not_independently_verified")
            deficit = calculate_deficit(target(), scenario)
            self.assertEqual(deficit["status"], "calculated")
            self.assertEqual(deficit["raw_deficit"], 18.0)
            self.assertEqual(deficit["deficit"], 18.0)

    def test_unentered_skus_keep_original_evidence_and_ambiguous_transit_is_provisional(self):
        first = balance(transit=9)
        second = balance("Systeme Electric", "OTHER", stock=22, transit=2)
        with test_directory() as directory:
            source_path = directory / "source.jsonl"
            output_path = directory / "scenario.jsonl"
            source_path.write_text("\n".join(json.dumps(row) for row in (first, second)) + "\n",
                                   encoding="utf-8")

            apply_stock_inputs(source_path, output_path, "2026-09-23",
                               {("IEK", "S1"): 7}, {})

            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[1], second)
            self.assertEqual(rows[0]["goods_in_transit"], first["goods_in_transit"])
            deficit = calculate_deficit(target(), rows[0])
            self.assertEqual(deficit["status"], "provisional")
            self.assertIn("goods_in_transit:ambiguous_date", deficit["provisional_reasons"])

    def test_date_mismatch_is_provisional(self):
        with test_directory() as directory:
            source_path = directory / "source.jsonl"
            output_path = directory / "scenario.jsonl"
            source_path.write_text(json.dumps(balance()) + "\n", encoding="utf-8")
            apply_stock_inputs(source_path, output_path, "2026-09-22",
                               {("IEK", "S1"): 7}, {("IEK", "S1"): 5})
            result = calculate_deficit(target(), json.loads(output_path.read_text(encoding="utf-8")))
            self.assertEqual(result["status"], "provisional")
            self.assertIn("current_stock:date_differs_from_planning_date",
                          result["provisional_reasons"])

    def test_repeated_user_entry_retains_original_workbook_evidence(self):
        original = balance(stock=12)
        first = apply_overrides(original, "2026-09-23", {("IEK", "S1"): 7}, {})
        second = apply_overrides(first, "2026-09-23", {("IEK", "S1"): 8}, {})
        self.assertEqual(second["current_stock"]["quantity"], 8)
        self.assertEqual(second["source_current_stock"], original["current_stock"])

    def test_undated_input_cannot_be_marked_confirmed_current(self):
        for invalid_date in (None, "", "2026-09-23T00:00:00"):
            with self.subTest(as_of_date=invalid_date), self.assertRaises(ValueError):
                apply_overrides(balance(), invalid_date, {("IEK", "S1"): 7}, {})
            with test_directory() as directory:
                source_path = directory / "source.jsonl"
                output_path = directory / "scenario.jsonl"
                source_path.write_text(json.dumps(balance()) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    apply_stock_inputs(source_path, output_path, invalid_date,
                                       {("IEK", "S1"): 7}, {})
                self.assertFalse(output_path.exists())

    def test_invalid_keys_or_dates_cannot_replace_existing_output(self):
        with test_directory() as directory:
            source_path = directory / "source.jsonl"
            output_path = directory / "scenario.jsonl"
            source_path.write_text(json.dumps(balance()) + "\n", encoding="utf-8")
            output_path.write_text("previous scenario", encoding="utf-8")
            for as_of_date, overrides in (
                ("2026-02-30", {("IEK", "S1"): 1}),
                ("2026-09-23", {("IEK", "ABSENT"): 1}),
            ):
                with self.subTest(date=as_of_date, overrides=overrides), self.assertRaises(ValueError):
                    apply_stock_inputs(source_path, output_path, as_of_date, overrides, {})
                self.assertEqual(output_path.read_text(encoding="utf-8"), "previous scenario")
            with self.assertRaises(ValueError):
                apply_stock_inputs(source_path, source_path, "2026-09-23",
                                   {("IEK", "S1"): 1}, {})


if __name__ == "__main__":
    unittest.main()

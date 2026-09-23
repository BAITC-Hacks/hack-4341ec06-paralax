"""Offline checks of the live experiment's inputs; no API calls in test suite."""

from __future__ import annotations

from scripts.benchmark_openai import REFERENCE, cases


def test_experiment_uses_synthetic_inputs_and_expected_scenarios() -> None:
    samples = cases()
    assert set(samples) == {"stable", "trend", "seasonal", "spike", "stockout"}
    for name, sample in samples.items():
        assert sample["planning_input"]["data_source"] == "synthetic"
        assert sample["forecast_request"]["data_source"] == "synthetic"
        assert sample["algorithm"]["recommended_quantity"] == REFERENCE[name]["order"]


def test_bulk_correction_and_stockout_are_explicit_experiment_inputs() -> None:
    samples = cases()
    spike = samples["spike"]["forecast_request"]["history"][-1]
    assert spike["observed_sales"] == 601
    assert spike["verified_one_off_excess"] == 570
    stockout = samples["stockout"]["forecast_request"]["history"][-1]
    assert stockout["observed_sales"] == 0
    assert stockout["confirmed_stockout_days"] == stockout["calendar_days"] == 31

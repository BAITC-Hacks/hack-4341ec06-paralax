"""Stage 7: inspect one SKU through every saved analytical stage.

All partner-derived output stays in ignored .analysis/. The generated page is
read-only: it never recomputes a purchase decision from missing information.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from clean_demand import SOURCE_COMMIT
from deficit import calculate_deficit
from order_recommendation import calculate_order

DEFAULT_INPUTS = {
    "stage1": Path(".analysis/clean-demand/all-skus.jsonl"),
    "stage2": Path(".analysis/base-demand/all-skus.jsonl"),
    "stage3": Path(".analysis/forecast/all-skus.jsonl"),
    "stage4": Path(".analysis/target-stock/all-skus.jsonl"),
    "stage5": Path(".analysis/deficit/all-skus.jsonl"),
    "stage6": Path(".analysis/orders/all-skus.jsonl"),
    "balances": Path(".analysis/balances/source-snapshot.jsonl"),
    "rules": Path(".analysis/packing-rules/source-rules.jsonl"),
}
OUTPUT_DIR = Path(".analysis/trace")


def load_selected(path: Path, keys: set[tuple[str, str]], label: str) -> tuple[dict, str]:
    """Stream a JSONL file, checking all unique keys while retaining selected rows."""
    found = {}
    seen = set()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                raise ValueError(f"Blank {label} JSONL line {line_number}")
            row = json.loads(line)
            key = (row["brand"], row["sku"])
            if key in seen:
                raise ValueError(f"Duplicate {label} SKU at line {line_number}: {key}")
            seen.add(key)
            if key in keys:
                found[key] = row
    return found, digest.hexdigest()


def same_number(actual: object, expected: object, label: str) -> None:
    """Require both values, or two nulls; zero is never interchangeable with null."""
    if actual is None or expected is None:
        if actual is not None or expected is not None:
            raise ValueError(f"{label} differs: {actual!r} versus {expected!r}")
        return
    if (isinstance(actual, bool) or isinstance(expected, bool)
            or not isinstance(actual, (int, float))
            or not isinstance(expected, (int, float))
            or not math.isfinite(actual) or not math.isfinite(expected)
            or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9)):
        raise ValueError(f"{label} differs: {actual!r} versus {expected!r}")


def validate_arithmetic(stages: dict[str, dict]) -> None:
    clean, base, forecast, target, deficit, order = (
        stages[f"stage{number}"] for number in range(1, 7)
    )
    periods = {item["period"]: item for item in clean["periods"]}
    if len(periods) != len(clean["periods"]):
        raise ValueError("Duplicate Stage-1 period")
    for period in clean["periods"]:
        adjusted = period.get("adjusted_sales")
        lost = period.get("estimated_lost_demand")
        observed = period.get("observed_demand")
        raw = period.get("raw_sales")
        excluded = period.get("excluded_one_off")
        same_number(observed, max(0.0, raw) if raw is not None else None,
                    f"Stage-1 observed demand {period['period']}")
        proposed_exclusion = sum(item["excluded_excess"] for item in
                                 period.get("outlier_documents", []))
        same_number(excluded,
                    min(observed or 0, proposed_exclusion)
                    if period.get("document_reconciled") else 0,
                    f"Stage-1 one-off exclusion {period['period']}")
        if observed is not None:
            same_number(adjusted, max(0.0, observed - excluded),
                        f"Stage-1 adjusted sales {period['period']}")
        clean_expected = (adjusted + lost if adjusted is not None and lost is not None
                          else lost if adjusted is None and lost is not None and lost > 0
                          else None)
        same_number(period.get("clean_demand"), clean_expected,
                    f"Stage-1 clean demand {period['period']}")

    selected = base["selected_periods"]
    total_weight = sum(item["raw_weight"] for item in selected)
    for item in selected:
        period = periods.get(item["period"])
        if period is None:
            raise ValueError(f"Stage-2 selected period missing in Stage 1: {item['period']}")
        same_number(item.get("clean_demand"), period.get("clean_demand"),
                    f"Stage-2 clean demand {item['period']}")
        same_number(item.get("normalized_weight"), item["raw_weight"] / total_weight,
                    f"Stage-2 normalized weight {item['period']}")
        same_number(item.get("weighted_contribution"),
                    item["clean_demand"] * item["normalized_weight"],
                    f"Stage-2 weighted contribution {item['period']}")
    same_number(base.get("base_demand_monthly"),
                sum(item["weighted_contribution"] for item in selected) if selected else None,
                "Stage-2 base demand")
    same_number(forecast.get("base_demand_monthly"), base.get("base_demand_monthly"),
                "Stage-3 base demand")

    forecast_months = {item["month"]: item for item in forecast["forecast_months"]}
    if len(forecast_months) != len(forecast["forecast_months"]):
        raise ValueError("Duplicate Stage-3 forecast month")
    for month in forecast["forecast_months"]:
        base_value = month.get("base_demand")
        trend = month.get("trend_adjustment")
        seasonality = month.get("seasonality_adjustment")
        final = month.get("final_forecast")
        same_number(base_value, base.get("base_demand_monthly"),
                    f"Stage-3 base demand {month['month']}")
        if base_value is not None:
            slope = forecast["trend"]["slope_per_month"]
            steps = month["steps_from_base_month"]
            expected_trend = max(-0.3 * base_value,
                                 min(0.3 * base_value, slope * steps))
            same_number(trend, expected_trend,
                        f"Stage-3 trend adjustment {month['month']}")
            seasonal_multiplier = month.get("seasonality_multiplier")
            if month.get("target_seasonality_index") is None:
                same_number(seasonal_multiplier, 1.0,
                            f"Stage-3 neutral seasonality {month['month']}")
            else:
                expected_multiplier = max(0.5, min(1.5,
                    month["target_seasonality_index"] /
                    month["base_window_seasonality_index"]))
                same_number(seasonal_multiplier, expected_multiplier,
                            f"Stage-3 seasonality multiplier {month['month']}")
            same_number(seasonality,
                        max(0.0, base_value + trend) * (seasonal_multiplier - 1),
                        f"Stage-3 seasonality adjustment {month['month']}")
        expected = (max(0.0, base_value + trend + seasonality)
                    if all(value is not None for value in (base_value, trend, seasonality)) else None)
        same_number(final, expected, f"Stage-3 forecast {month['month']}")
    contributions = []
    for part in target["forecast_months_in_lead_time"]:
        month = forecast_months.get(part["month"])
        if month is None:
            raise ValueError(f"Stage-4 forecast month absent from Stage 3: {part['month']}")
        same_number(part.get("monthly_forecast"), month.get("final_forecast"),
                    f"Stage-4 monthly forecast {part['month']}")
        contribution = part.get("demand_contribution")
        monthly = part.get("monthly_forecast")
        same_number(contribution,
                    monthly * part["covered_days"] / part["days_in_month"]
                    if monthly is not None else None,
                    f"Stage-4 lead-time contribution {part['month']}")
        contributions.append(contribution)
    lead_demand = sum(contributions) if contributions and all(
        value is not None for value in contributions) else None
    same_number(target.get("lead_time_demand"), lead_demand, "Stage-4 lead-time demand")
    average_daily = (lead_demand / target["lead_time_days"]
                     if lead_demand is not None else None)
    same_number(target.get("average_daily_forecast"), average_daily,
                "Stage-4 average daily forecast")
    safety = target.get("safety_stock")
    same_number(safety, average_daily * target["safety_stock_days"]
                if average_daily is not None else None, "Stage-4 safety stock")
    same_number(target.get("target_stock"), lead_demand + safety
                if lead_demand is not None and safety is not None else None,
                "Stage-4 target stock")
    same_number(deficit.get("target_stock"), target.get("target_stock"),
                "Stage-5 target stock")
    stock = (deficit.get("current_stock") or {}).get("quantity")
    transit = (deficit.get("goods_in_transit") or {}).get("quantity")
    raw = (target["target_stock"] - stock - transit
           if all(value is not None for value in (target.get("target_stock"), stock, transit))
           else None)
    same_number(deficit.get("raw_deficit"), raw, "Stage-5 raw deficit")
    same_number(deficit.get("deficit"), max(0.0, raw) if raw is not None else None,
                "Stage-5 clipped deficit")
    for field in ("target_stock", "raw_deficit", "deficit"):
        same_number(order.get(field), deficit.get(field), f"Stage-6 {field}")
    if order.get("current_stock") != deficit.get("current_stock") \
            or order.get("goods_in_transit") != deficit.get("goods_in_transit"):
        raise ValueError("Stage-6 balance evidence differs from Stage 5")
    order_rule = order.get("packing_rule")
    if order_rule and order_rule.get("status") == "missing" and not order_rule.get("source_commit"):
        order_rule = None
    expected_order = calculate_order(deficit, target, order_rule,
                                     deficit_sha256=order.get("deficit_sha256", ""),
                                     rules_sha256=order.get("rules_sha256", ""))
    for field, expected in expected_order.items():
        if field not in order or order[field] != expected:
            raise ValueError(f"Stage-6 {field} differs from reproducible calculation")


def assemble_trace(stages: dict[str, dict], hashes: dict[str, str],
                   balance_record: dict | None = None,
                   source_rule_record: dict | None = None) -> dict:
    """Verify complete lineage and handoffs, then retain unrounded stage records."""
    required = {f"stage{i}" for i in range(1, 7)} | {"balances", "rules"}
    if not required <= hashes.keys() or not {f"stage{i}" for i in range(1, 7)} <= stages.keys():
        raise ValueError("Incomplete Stage-1..6 lineage")
    key = (stages["stage1"]["brand"], stages["stage1"]["sku"])
    for number in range(1, 7):
        record = stages[f"stage{number}"]
        if key != (record["brand"], record["sku"]):
            raise ValueError(f"Stage-{number} brand/SKU key differs")
        if record.get("source_commit") != SOURCE_COMMIT:
            raise ValueError(f"Stage-{number} source commit differs")
    expected_hashes = {
        "stage2": {"upstream_sha256": "stage1"},
        "stage3": {"stage1_sha256": "stage1", "stage2_sha256": "stage2"},
        "stage4": {"stage1_sha256": "stage1", "stage2_sha256": "stage2",
                   "upstream_sha256": "stage3"},
        "stage5": {"stage1_sha256": "stage1", "stage2_sha256": "stage2",
                   "stage3_sha256": "stage3", "target_sha256": "stage4",
                   "balance_sha256": "balances"},
        "stage6": {"target_sha256": "stage4", "balance_sha256": "balances",
                   "deficit_sha256": "stage5", "rules_sha256": "rules"},
    }
    for stage_name, fields in expected_hashes.items():
        record = stages[stage_name]
        for field, upstream in fields.items():
            if record.get(field) != hashes[upstream]:
                raise ValueError(f"{stage_name}.{field} does not match {upstream} SHA-256")
    planning_date = stages["stage4"].get("planning_date")
    if stages["stage5"].get("planning_date") != planning_date \
            or stages["stage6"].get("planning_date") != planning_date:
        raise ValueError("Planning dates differ across Stages 4–6")
    if balance_record is None:
        raise ValueError(f"Balance source lacks {key[0]} / {key[1]}")
    if key != (balance_record["brand"], balance_record["sku"]):
        raise ValueError("Balance brand/SKU key differs")
    deficit = stages["stage5"]
    for field in ("current_stock", "goods_in_transit", "historical_stock",
                  "source_current_stock", "source_goods_in_transit"):
        if balance_record.get(field) != deficit.get(field):
            raise ValueError(f"Stage-5 {field} differs from balance source")
    expected_deficit = calculate_deficit(stages["stage4"], balance_record,
                                         hashes["stage4"], hashes["balances"])
    for field, expected in expected_deficit.items():
        if field not in stages["stage5"] or stages["stage5"][field] != expected:
            raise ValueError(f"Stage-5 {field} differs from reproducible calculation")
    order_rule = stages["stage6"].get("packing_rule") or {}
    if source_rule_record is not None and source_rule_record != order_rule:
        raise ValueError("Stage-6 packing rule differs from source rule")
    if source_rule_record is None and order_rule.get("status") != "missing":
        raise ValueError("Stage-6 packing rule has no source rule")
    validate_arithmetic(stages)
    return {
        "brand": key[0], "sku": key[1], "name": stages["stage1"].get("name", ""),
        "unit": stages["stage1"].get("unit"),
        "source_commit": SOURCE_COMMIT,
        "planning_date": planning_date,
        "status": stages["stage6"].get("status"),
        "lineage": {"sha256": hashes, "verified": True},
        **stages,
    }


def atomic_write_text(path: Path, contents: str) -> None:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix="trace-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(contents)
        os.replace(temp_path, path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def trace_stem(brand: str, sku: str) -> str:
    safe_sku = re.sub(r"[^A-Za-z0-9_-]", "-", sku)
    if safe_sku != sku:
        safe_sku += "-" + hashlib.sha256(sku.encode("utf-8")).hexdigest()[:8]
    return ("iek-" if brand == "IEK" else "systeme-") + safe_sku


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", required=True, choices=("IEK", "Systeme Electric"))
    parser.add_argument("--sku", required=True, action="append", help="SKU to trace; repeatable")
    for name, default in DEFAULT_INPUTS.items():
        parser.add_argument(f"--{name}", type=Path, default=default)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    keys = {(args.brand, sku) for sku in args.sku}
    if len(keys) != len(args.sku):
        parser.error("Duplicate --sku")
    paths = {name: getattr(args, name) for name in DEFAULT_INPUTS}
    for name, path in paths.items():
        if not path.is_file():
            parser.error(f"Required {name} input is missing: {path}")
    try:
        selected, hashes = {}, {}
        for name, path in paths.items():
            selected[name], hashes[name] = load_selected(path, keys, name)
        traces = []
        for key in sorted(keys):
            stages = {}
            for number in range(1, 7):
                name = f"stage{number}"
                if key not in selected[name]:
                    raise ValueError(f"{name} lacks {key[0]} / {key[1]}")
                stages[name] = selected[name][key]
            traces.append(assemble_trace(stages, hashes, selected["balances"].get(key),
                                         selected["rules"].get(key)))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    from trace_page import render_trace_html

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for trace in traces:
        stem = trace_stem(trace["brand"], trace["sku"])
        json_path = args.output_dir / f"{stem}.json"
        html_path = args.output_dir / f"{stem}.html"
        atomic_write_text(json_path, json.dumps(trace, ensure_ascii=False, indent=2, allow_nan=False))
        temp_html = html_path.with_suffix(".html.tmp")
        try:
            render_trace_html(trace, temp_html)
            os.replace(temp_html, html_path)
        except Exception:
            temp_html.unlink(missing_ok=True)
            raise
        print(f"{trace['brand']} / {trace['sku']}: {html_path} ({trace['status']})")


if __name__ == "__main__":
    main()

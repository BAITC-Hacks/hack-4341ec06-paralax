"""JSON Schema and cross-reference validation for the HTTP boundary."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
Issue = dict[str, str]
Json = dict[str, Any]


@lru_cache(maxsize=3)
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_issues(payload: Any, name: str) -> list[Issue]:
    errors = sorted(
        _validator(name).iter_errors(payload),
        key=lambda error: ".".join(str(part) for part in error.path),
    )
    return [
        {"field": ".".join(str(part) for part in error.path) or "$", "reason": error.message}
        for error in errors
    ]


def validate_planning_input(payload: Any) -> list[Issue]:
    issues = schema_issues(payload, "planning-input")
    if issues:
        return issues

    supplier_ids: set[str] = set()
    for index, supplier in enumerate(payload["suppliers"]):
        supplier_id = supplier["supplier_id"]
        if supplier_id in supplier_ids:
            issues.append(
                {"field": f"suppliers.{index}.supplier_id", "reason": "duplicate supplier"}
            )
        supplier_ids.add(supplier_id)

    product_skus: set[str] = set()
    as_of_date = date.fromisoformat(payload["as_of_date"])
    for index, product in enumerate(payload["products"]):
        sku = product["sku"]
        if sku in product_skus:
            issues.append({"field": f"products.{index}.sku", "reason": "duplicate SKU"})
        product_skus.add(sku)
        if product["supplier_id"] not in supplier_ids:
            issues.append({"field": f"products.{index}.supplier_id", "reason": "unknown supplier"})
        stock_date = product.get("stock_as_of_date")
        if stock_date and date.fromisoformat(stock_date) > as_of_date:
            issues.append(
                {"field": f"products.{index}.stock_as_of_date", "reason": "after as_of_date"}
            )
        if (
            "shipments" in product
            and sum(shipment["quantity"] for shipment in product["shipments"])
            != product["goods_in_transit"]
        ):
            issues.append(
                {"field": f"products.{index}.shipments", "reason": "transit quantity mismatch"}
            )

    seen_sales: set[tuple[str, str, str, str | None]] = set()
    for index, sale in enumerate(payload["sales"]):
        if sale["sku"] not in product_skus:
            issues.append({"field": f"sales.{index}.sku", "reason": "unknown SKU"})
        if date.fromisoformat(sale["date"]) > as_of_date:
            issues.append({"field": f"sales.{index}.date", "reason": "after as_of_date"})
        identity = (sale["sku"], sale["date"], sale["document_id"], sale.get("warehouse_id"))
        if identity in seen_sales:
            issues.append({"field": f"sales.{index}", "reason": "duplicate document/SKU/date"})
        seen_sales.add(identity)

    for index, stockout in enumerate(payload["stockouts"]):
        if stockout["sku"] not in product_skus:
            issues.append({"field": f"stockouts.{index}.sku", "reason": "unknown SKU"})
        start = date.fromisoformat(stockout["start_date"])
        end = date.fromisoformat(stockout["end_date"])
        if end < start:
            issues.append({"field": f"stockouts.{index}.end_date", "reason": "before start_date"})
        if end > as_of_date:
            issues.append({"field": f"stockouts.{index}.end_date", "reason": "after as_of_date"})

    for index, signal in enumerate(payload.get("stockout_signals", [])):
        if signal["sku"] not in product_skus:
            issues.append({"field": f"stockout_signals.{index}.sku", "reason": "unknown SKU"})
        if signal["month"] > payload["as_of_date"][:7]:
            issues.append({"field": f"stockout_signals.{index}.month", "reason": "future month"})

    seen_months: set[tuple[str, str]] = set()
    for index, point in enumerate(payload.get("monthly_history", [])):
        month = date.fromisoformat(point["month"])
        key = (point["sku"], point["month"])
        if point["sku"] not in product_skus or month.day != 1 or month >= as_of_date.replace(day=1):
            issues.append(
                {"field": f"monthly_history.{index}.month", "reason": "invalid month or SKU"}
            )
        if key in seen_months:
            issues.append(
                {"field": f"monthly_history.{index}.month", "reason": "duplicate SKU/month"}
            )
        seen_months.add(key)

    if payload.get("history_start_date", "0001") > payload.get("history_end_date", "9999"):
        issues.append({"field": "history_end_date", "reason": "before history_start_date"})
    if payload.get("history_end_date", payload["as_of_date"]) > payload["as_of_date"]:
        issues.append({"field": "history_end_date", "reason": "after as_of_date"})

    return issues


def validate_planning_result(payload: Any) -> list[Issue]:
    issues = schema_issues(payload, "planning-result")
    if issues:
        return issues
    seen: set[str] = set()
    for index, row in enumerate(payload["recommendations"]):
        sku = row["sku"]
        if sku in seen:
            issues.append({"field": f"recommendations.{index}.sku", "reason": "duplicate SKU"})
        seen.add(sku)
    return issues


def validate_result_against_input(result: dict[str, Any], payload: dict[str, Any]) -> list[Issue]:
    products = {product["sku"]: product for product in payload["products"]}
    suppliers = {supplier["supplier_id"]: supplier for supplier in payload["suppliers"]}
    issues: list[Issue] = []
    for index, row in enumerate(result["recommendations"]):
        product = products.get(row["sku"])
        if product is None:
            issues.append({"field": f"recommendations.{index}.sku", "reason": "unknown input SKU"})
            continue
        if row["supplier_id"] != product["supplier_id"]:
            issues.append(
                {"field": f"recommendations.{index}.supplier_id", "reason": "supplier mismatch"}
            )
        for field in ("current_stock",):
            if row["factors"][field] != product[field]:
                issues.append(
                    {
                        "field": f"recommendations.{index}.factors.{field}",
                        "reason": "input mismatch",
                    }
                )
        end = date.fromisoformat(payload["as_of_date"]) + timedelta(
            days=suppliers[product["supplier_id"]]["lead_time_days"] + payload["review_period_days"]
        )
        expected_late = sum(
            shipment["quantity"]
            for shipment in product.get("shipments", [])
            if date.fromisoformat(shipment["expected_date"]) > end
        )
        expected_eligible = product["goods_in_transit"] - expected_late
        if (
            row["factors"]["goods_in_transit"] != expected_eligible
            or row["factors"].get("excluded_late_transit", 0) != expected_late
        ):
            issues.append(
                {
                    "field": f"recommendations.{index}.factors.goods_in_transit",
                    "reason": "input transit mismatch",
                }
            )
    return issues


def validate_schema(value: Json, name: str) -> None:
    issues = schema_issues(value, name)
    if issues:
        raise ValueError(str(issues))
    json.dumps(value, allow_nan=False)


def validate_input(data: Json) -> None:
    issues = validate_planning_input(data)
    if issues:
        raise ValueError(str(issues))
    json.dumps(data, allow_nan=False)


def integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected a numeric quantity, got {value!r}")
    if not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError(f"{label}: expected a nonnegative integer, got {value!r}")
    return int(value)

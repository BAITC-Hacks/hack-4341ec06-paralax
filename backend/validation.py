"""JSON Schema and cross-reference validation for the HTTP boundary."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
Issue = dict[str, str]


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

    for index, sale in enumerate(payload["sales"]):
        if sale["sku"] not in product_skus:
            issues.append({"field": f"sales.{index}.sku", "reason": "unknown SKU"})
        if date.fromisoformat(sale["date"]) > as_of_date:
            issues.append({"field": f"sales.{index}.date", "reason": "after as_of_date"})

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
        for field in ("current_stock", "goods_in_transit"):
            if row["factors"][field] != product[field]:
                issues.append(
                    {
                        "field": f"recommendations.{index}.factors.{field}",
                        "reason": "input mismatch",
                    }
                )
    return issues

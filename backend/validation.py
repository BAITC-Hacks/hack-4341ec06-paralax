"""JSON contract and cross-record validation shared by import and planning."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
Json = dict[str, Any]


def validate_schema(value: Json, name: str) -> None:
    schema = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text("utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    # JSON Schema's number checker accepts NaN; JSON transport must not.
    json.dumps(value, allow_nan=False)


def validate_input(data: Json) -> None:
    validate_schema(data, "planning-input")
    skus = [p["sku"] for p in data["products"]]
    suppliers = [s["supplier_id"] for s in data["suppliers"]]
    if len(set(skus)) != len(skus) or len(set(suppliers)) != len(suppliers):
        raise ValueError("Duplicate SKU or supplier_id")
    cutoff = date.fromisoformat(data["as_of_date"])
    for p in data["products"]:
        if p["supplier_id"] not in suppliers:
            raise ValueError(f"Unknown supplier for {p['sku']}")
        if p.get("stock_as_of_date", data["as_of_date"]) > data["as_of_date"]:
            raise ValueError("Stock date is after planning cutoff")
        if "shipments" in p and sum(s["quantity"] for s in p["shipments"]) != p["goods_in_transit"]:
            raise ValueError("Shipment quantities disagree with goods_in_transit")
    seen: set[tuple[Any, ...]] = set()
    for s in data["sales"]:
        if s["sku"] not in skus or date.fromisoformat(s["date"]) > cutoff:
            raise ValueError("Sale has unknown SKU or future date")
        identity = (
            s["sku"],
            s["date"],
            s.get("document_id", s.get("customer_id")),
            s.get("warehouse_id"),
        )
        if identity in seen:
            raise ValueError("Duplicate sales document/SKU/warehouse/date")
        seen.add(identity)
    seen_months: set[tuple[str, str]] = set()
    for point in data.get("monthly_history", []):
        month = date.fromisoformat(point["month"])
        key = (point["sku"], point["month"])
        if point["sku"] not in skus or month.day != 1 or month >= cutoff.replace(day=1):
            raise ValueError("Monthly history must use completed months and known SKU")
        if key in seen_months:
            raise ValueError("Duplicate SKU/month")
        seen_months.add(key)
    for s in data["stockouts"]:
        if (
            s["sku"] not in skus
            or s["start_date"] > s["end_date"]
            or s["end_date"] > data["as_of_date"]
        ):
            raise ValueError("Invalid stockout interval")
    if data.get("history_start_date", "0001") > data.get("history_end_date", "9999"):
        raise ValueError("History start must precede end")
    if data.get("history_end_date", data["as_of_date"]) > data["as_of_date"]:
        raise ValueError("History extends past cutoff")


def integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected a numeric quantity, got {value!r}")
    if not math.isfinite(value) or value < 0 or int(value) != value:
        raise ValueError(f"{label}: expected a nonnegative integer, got {value!r}")
    return int(value)

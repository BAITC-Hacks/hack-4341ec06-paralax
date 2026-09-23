"""Human-only state transitions; no supplier network side effects."""

from __future__ import annotations

from copy import deepcopy

from backend.validation import Json, integer, validate_schema


def select_quantity(result: Json, sku: str, quantity: int) -> Json:
    validate_schema(result, "planning-result")
    if result["status"] != "draft":
        raise ValueError("Approved plans cannot be edited")
    edited = deepcopy(result)
    for row in edited["recommendations"]:
        if row["sku"] == sku:
            row["selected_quantity"] = integer(quantity, "selected_quantity")
            return edited
    raise ValueError(f"Unknown SKU: {sku}")


def approve(result: Json) -> Json:
    validate_schema(result, "planning-result")
    approved = deepcopy(result)
    approved["status"] = "approved"
    return approved

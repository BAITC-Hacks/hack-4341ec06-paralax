"""Pure, reversible operations on a procurement draft."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class RunStateError(ValueError):
    """The requested change is not allowed for this run state."""


class RecommendationNotFound(ValueError):
    """The requested SKU is not part of this run."""


def select_quantity(run: dict[str, Any], sku: str, quantity: int) -> dict[str, Any]:
    if run["status"] != "draft":
        raise RunStateError("approved runs cannot be edited")
    if type(quantity) is not int or quantity < 0:
        raise ValueError("selected_quantity must be a non-negative integer")
    updated = deepcopy(run)
    for row in updated["recommendations"]:
        if row["sku"] == sku:
            row["selected_quantity"] = quantity
            return updated
    raise RecommendationNotFound(sku)


def approve(run: dict[str, Any]) -> dict[str, Any]:
    approved = deepcopy(run)
    approved["status"] = "approved"
    return approved

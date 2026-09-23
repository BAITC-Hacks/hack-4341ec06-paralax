"""Validate an optional AI explanation and keep a deterministic fallback."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.validation import schema_issues

logger = logging.getLogger(__name__)
Explainer = Callable[[dict[str, Any]], dict[str, Any]]
NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?(?![\w])")


def fallback_explanation(row: dict[str, Any]) -> dict[str, Any]:
    factors = row["factors"]
    forecast = factors["forecast_during_coverage"]
    safety = factors["safety_stock"]
    stock = factors["current_stock"]
    transit = factors["goods_in_transit"]
    risk = (
        "Проверьте неполные или предположительные данные перед утверждением."
        if any(flag in row["flags"] for flag in ("missing_data", "suspected_stockout"))
        else "Проверьте исходные остатки и срок поставки перед утверждением."
    )
    return {
        "summary": (
            f"Рекомендовано заказать {row['recommended_quantity']} шт. по расчётным факторам."
        ),
        "drivers": [
            f"Прогноз на горизонт: {forecast} шт.; страховой запас: {safety} шт.",
            f"Текущий остаток: {stock} шт.; товар в пути: {transit} шт.",
        ],
        "risk": risk,
        "review_question": "Подтверждаете количество и дату остатка для этого артикула?",
        "evidence_keys": [
            "recommended_quantity",
            "forecast_during_coverage",
            "safety_stock",
            "current_stock",
            "goods_in_transit",
        ],
        "source": "fallback",
    }


def _numeric_claims_supported(candidate: dict[str, Any], row: dict[str, Any]) -> bool:
    values = [row["recommended_quantity"], row["selected_quantity"], *row["factors"].values()]
    allowed: set[Decimal] = set()
    for value in values:
        if type(value) in (int, float):
            allowed.add(Decimal(str(value)))
    text_parts = [
        candidate["summary"],
        *candidate["drivers"],
        candidate["risk"],
        candidate["review_question"],
    ]
    for claim in NUMBER.findall(" ".join(text_parts)):
        try:
            if Decimal(claim.replace(",", ".")) not in allowed:
                return False
        except InvalidOperation:
            return False
    return True


def explain_recommendation(
    row: dict[str, Any], explainer: Explainer | None = None
) -> dict[str, Any]:
    if explainer is None:
        return fallback_explanation(row)
    try:
        candidate = explainer(deepcopy(row))
        if not isinstance(candidate, dict):
            raise ValueError("explanation must be an object")
        candidate = {**candidate, "source": candidate.get("source", "openai")}
        if schema_issues(candidate, "explanation"):
            raise ValueError("explanation violates schema")
        allowed_keys = set(row["factors"]) | {"recommended_quantity", "selected_quantity"}
        if not set(candidate["evidence_keys"]).issubset(allowed_keys):
            raise ValueError("explanation cites unknown evidence")
        if not _numeric_claims_supported(candidate, row):
            raise ValueError("explanation contains unsupported numbers")
        return candidate
    except Exception:
        logger.exception("AI explanation rejected; using deterministic fallback")
        return fallback_explanation(row)

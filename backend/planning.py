"""Pure planning function: validated input -> reproducible JSON draft."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median

from backend.forecast import Point, month_days, next_month, predict, select_model
from backend.validation import Json, validate_input, validate_schema


def lost_month(points: list[Point], target: date, days: int) -> float | None:
    """Estimate censored demand from observed past only, never train on imputation."""
    past = [(d, v) for d, v in points if d < target and v is not None]
    comparable = [v for d, v in past if d.month == target.month]
    values = comparable or [v for _, v in past][-6:]
    return mean(values) * days if values else None


def anomalies(sales: list[Json]) -> tuple[dict[str, float], dict[str, float]]:
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for s in sales:
        grouped[(s["date"], str(s.get("document_id", s.get("customer_id", ""))))] += s["quantity"]
    past: list[tuple[date, float]] = []
    excess: dict[str, float] = defaultdict(float)
    totals: dict[str, float] = defaultdict(float)
    for (stamp, _), quantity in sorted(grouped.items()):
        current = date.fromisoformat(stamp)
        history = [q for d, q in past if 0 < (current - d).days <= 30]
        if len(history) >= 3:
            typical = median(history)
            if quantity > 5 * typical:
                excess[stamp[:7]] += quantity - typical
        totals[stamp[:7]] += quantity
        past.append((current, quantity))
    return dict(excess), dict(totals)


def history(data: Json, sku: str) -> tuple[list[Point], float, float, list[str], list[str]]:
    sales = [s for s in data["sales"] if s["sku"] == sku]
    excess, totals = anomalies(sales)
    flags = ["one_off_sale"] if excess else []
    warnings: list[str] = []
    monthly = [p for p in data.get("monthly_history", []) if p["sku"] == sku]
    confirmed: set[date] = set()
    for interval in data["stockouts"]:
        if interval["sku"] != sku:
            continue
        if interval.get("certainty", "confirmed") == "suspected":
            flags.append("suspected_stockout")
            continue
        start, end = (
            date.fromisoformat(interval["start_date"]),
            date.fromisoformat(interval["end_date"]),
        )
        confirmed.update(start + timedelta(days=i) for i in range((end - start).days + 1))
    if any(date.fromisoformat(s["date"]) in confirmed for s in sales):
        raise ValueError(f"{sku}: sales overlap a confirmed full-day stockout")
    adjusted: list[Point] = []
    lost = 0.0
    applied_excess = 0.0
    if monthly:
        by_month = {date.fromisoformat(p["month"]): p for p in monthly}
        current, last = min(by_month), max(by_month)
        while current <= last:
            p = by_month.get(current)
            if p is None or p["quantity"] is None:
                adjusted.append((current, None))
                warnings.append("Пропуск месячной истории сохранён как неизвестный спрос.")
                current = next_month(current)
                continue
            qty = float(p["quantity"])
            key = current.strftime("%Y-%m")
            if excess.get(key, 0):
                if math.isclose(totals.get(key, 0), qty, abs_tol=1e-6):
                    qty -= excess[key]
                    applied_excess += excess[key]
                else:
                    warnings.append("Сумма документов не совпала с месячной: аномалия не вычтена.")
            days = month_days(current)
            unavailable = sum(current <= d < next_month(current) for d in confirmed)
            if unavailable == days:
                if float(p["quantity"]) > 0:
                    raise ValueError(
                        f"{sku}: positive monthly sales during full confirmed stockout"
                    )
                estimate = lost_month(adjusted, current, days)
                if estimate is None:
                    warnings.append(
                        "Полный stockout: нет предыстории для оценки упущенного спроса."
                    )
                else:
                    lost += estimate
                    flags.append("stockout_adjustment")
                    warnings.append(
                        "Упущенный спрос при полном stockout оценён по прошлым периодам."
                    )
                adjusted.append((current, None))
                current = next_month(current)
                continue
            if p["opening_stock"] == 0:
                flags.append("suspected_stockout")
                if qty == 0:
                    adjusted.append((current, None))
                    warnings.append("Нулевые продажи при нулевом остатке: спрос неизвестен.")
                    current = next_month(current)
                    continue
            rate = qty / (days - unavailable)
            lost += rate * unavailable
            adjusted.append((current, rate))
            current = next_month(current)
    elif sales:
        start = date.fromisoformat(data.get("history_start_date", min(s["date"] for s in sales)))
        end = date.fromisoformat(data.get("history_end_date", max(s["date"] for s in sales)))
        grouped: dict[date, float] = defaultdict(float)
        for s in sales:
            d = date.fromisoformat(s["date"])
            if start <= d <= end:
                grouped[d.replace(day=1)] += s["quantity"]
        current = start.replace(day=1)
        while current <= end:
            first, last = max(current, start), min(next_month(current) - timedelta(days=1), end)
            days = (last - first).days + 1
            unavailable = sum(first <= d <= last for d in confirmed)
            correction = excess.get(current.strftime("%Y-%m"), 0)
            applied_excess += correction
            qty = max(0, grouped[current] - correction)
            partial_rate = qty / (days - unavailable) if days > unavailable else None
            if partial_rate is not None:
                lost += partial_rate * unavailable
            else:
                estimate = lost_month(adjusted, current, days)
                if estimate is None:
                    warnings.append(
                        "Полный stockout: нет предыстории для оценки упущенного спроса."
                    )
                else:
                    lost += estimate
                    flags.append("stockout_adjustment")
                    warnings.append(
                        "Упущенный спрос при полном stockout оценён по прошлым периодам."
                    )
            adjusted.append((current, partial_rate))
            current = next_month(current)
        if "history_start_date" not in data or "history_end_date" not in data:
            warnings.append("Экспозиция синтетических продаж ограничена первой/последней записью.")
    if lost > 0:
        flags.append("stockout_adjustment")
    if "suspected_stockout" in flags:
        warnings.append("Нулевой месячный остаток: дни дефицита и упущенный спрос не установлены.")
    if len([v for _, v in adjusted if v is not None]) < 24:
        flags.append("short_history")
    if not adjusted or not any(v is not None for _, v in adjusted):
        raise ValueError(f"{sku}: no observed demand history")
    return adjusted, lost, applied_excess, flags, warnings


def plan(planning_input: Json) -> Json:
    validate_input(planning_input)
    data = planning_input
    as_of = date.fromisoformat(data["as_of_date"])
    suppliers = {s["supplier_id"]: s for s in data["suppliers"]}
    recommendations = []
    for product in data["products"]:
        sku = product["sku"]
        points, lost, anomaly_qty, flags, warnings = history(data, sku)
        warnings.extend(product.get("quality_warnings", []))
        model, scores, count = select_model(points)
        if not scores:
            warnings.append("Недостаточно временных срезов для выбора модели по валидации.")
        supplier = suppliers[product["supplier_id"]]
        lead = supplier["lead_time_days"]
        coverage = lead + data["review_period_days"]
        base = mean([v for _, v in points if v is not None][-6:])
        rates = [predict(model, points, as_of + timedelta(days=i)) for i in range(1, coverage + 1)]
        if base == 0 and mean(rates) > 0:
            base = mean(rates)
        seasonal = mean(rates) / base if model == "seasonal" and base else 1.0
        trend = mean(rates) / base if model != "seasonal" and base else 1.0
        growth = 1 + product["growth_forecast_pct"] / 100
        demand = sum(rates) * growth
        safety = demand / coverage * data.get("safety_stock_days", 7)
        transit = product["goods_in_transit"]
        late = 0
        if "shipments" in product:
            limit = as_of + timedelta(days=coverage)
            late = sum(
                s["quantity"]
                for s in product["shipments"]
                if date.fromisoformat(s["expected_date"]) > limit
            )
            if any(date.fromisoformat(s["expected_date"]) < as_of for s in product["shipments"]):
                warnings.append("Есть просроченный транзит: требуется проверка поступления.")
            transit -= late
        elif transit:
            warnings.append("ETA транзита неизвестна; принято поступление внутри горизонта.")
        stock = product["current_stock"]
        quantity = max(0, math.ceil(demand + safety - stock - transit - 1e-9))
        if quantity:
            multiple = product.get("order_multiple", 1)
            quantity = (
                math.ceil(max(quantity, product.get("minimum_order_quantity", 0)) / multiple)
                * multiple
            )
        daily = demand / coverage
        urgency = (
            "critical"
            if stock == 0 and daily
            else "high"
            if daily and stock / daily < lead
            else "medium"
            if quantity
            else "low"
        )
        if model == "seasonal":
            flags.append("seasonality")
        if product["growth_forecast_pct"] or model == "trend" and not math.isclose(trend, 1):
            flags.append("growth")
        if product.get("stock_as_of_date", data["as_of_date"]) < data["as_of_date"]:
            warnings.append(
                "Остаток устарел относительно даты расчёта; поступления не восстановлены."
            )
        if warnings:
            flags.append("missing_data")
        factors: Json = {
            "regular_daily_demand": base,
            "seasonality_multiplier": seasonal,
            "trend_multiplier": trend,
            "external_growth_multiplier": growth,
            "estimated_lost_demand": lost,
            "coverage_days": coverage,
            "forecast_during_coverage": demand,
            "safety_stock": safety,
            "current_stock": stock,
            "goods_in_transit": transit,
            "lead_time_days": lead,
            "excluded_late_transit": late,
            "anomaly_excess_quantity": anomaly_qty,
        }
        for field in ("stock_as_of_date", "stock_source"):
            if field in product:
                factors[field] = product[field]
        recommendations.append(
            {
                "sku": sku,
                "name": product["name"],
                "category": product["category"],
                "supplier_id": supplier["supplier_id"],
                "supplier_name": supplier["name"],
                "recommended_quantity": quantity,
                "selected_quantity": quantity,
                "urgency": urgency,
                "factors": factors,
                "flags": sorted(set(flags)),
                "reason": f"Прогноз {demand:.2f} + запас {safety:.2f} − остаток {stock} "
                f"− транзит в горизонте {transit}; после округления и ограничений: {quantity}.",
                "diagnostics": {
                    "model": model,
                    "validation_mae": scores.get(model),
                    "validation_points": count,
                    "candidate_mae": scores,
                    "unit": product.get("unit", "базовая единица"),
                    "quality_warnings": sorted(set(warnings)),
                },
            }
        )
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    result: Json = {
        "run_id": f"plan-v02-{digest}",
        "as_of_date": data["as_of_date"],
        "warehouse_id": data["warehouse_id"],
        "status": "draft",
        "data_source": data.get("data_source", "synthetic"),
        "recommendations": recommendations,
        "source_files": data.get("source_files", []),
        "assumptions": data.get("assumptions", []),
    }
    validate_schema(result, "planning-result")
    return result

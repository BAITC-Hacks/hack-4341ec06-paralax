"""Small auditable forecasting models; rolling-origin selection, no random split."""

from __future__ import annotations

import calendar
from datetime import date
from statistics import mean

Point = tuple[date, float | None]
MODELS = ("mean6", "ses", "trend", "seasonal", "tsb")


def month_days(month: date) -> int:
    return calendar.monthrange(month.year, month.month)[1]


def next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def available(model: str, points: list[Point]) -> bool:
    rates = [v for _, v in points if v is not None]
    if not rates:
        return False
    if model == "seasonal":
        return all(
            sum(d.month == m and v is not None for d, v in points) >= 2 for m in range(1, 13)
        )
    if model == "tsb":
        return len(rates) == len(points) and len(rates) >= 6 and rates.count(0) / len(rates) >= 0.3
    if model == "trend":
        return len(points) >= 6 and all(v is not None for _, v in points[-6:])
    return True


def predict(model: str, points: list[Point], target: date) -> float:
    values = [v for _, v in points if v is not None]
    if not values:
        return 0.0
    base = mean(values[-6:])
    if model == "seasonal":
        return mean([v for d, v in points if d.month == target.month and v is not None])
    if model == "ses":
        level = values[0]
        for value in values[1:]:
            level = 0.3 * value + 0.7 * level
        return level
    if model == "trend":
        recent = values[-6:]
        # At least four of five changes must agree; an isolated spike cannot create a trend.
        diffs = [b - a for a, b in zip(recent, recent[1:], strict=False)]
        direction = (
            1 if sum(d > 0 for d in diffs) >= 4 else -1 if sum(d < 0 for d in diffs) >= 4 else 0
        )
        if direction:
            slope = (recent[-1] - recent[0]) / 5
            steps = max(
                1, (target.year - points[-1][0].year) * 12 + target.month - points[-1][0].month
            )
            return max(0.5 * base, min(1.5 * base, recent[-1] + slope * min(steps, 3)))
        return base
    if model == "tsb":
        nonzero = next((v for v in values if v > 0), 0.0)
        probability = 1.0 if values[0] > 0 else 0.0
        size = nonzero
        for value in values:
            probability = 0.2 * (value > 0) + 0.8 * probability
            if value > 0:
                size = 0.2 * value + 0.8 * size
        return probability * size
    return base


def select_model(points: list[Point]) -> tuple[str, dict[str, float], int]:
    origins = [i for i in range(max(6, len(points) - 6), len(points)) if points[i][1] is not None]
    scores: dict[str, float] = {}
    for model in MODELS:
        if not available(model, points):
            continue
        eligible = all(
            all(any(d.month == m and v is not None for d, v in points[:i]) for m in range(1, 13))
            if model == "seasonal"
            else available(model, points[:i])
            for i in origins
        )
        if origins and eligible:
            scores[model] = mean(
                abs(predict(model, points[:i], points[i][0]) - actual)
                for i in origins
                if (actual := points[i][1]) is not None
            )
    if scores:
        return min(scores, key=lambda m: (scores[m], MODELS.index(m))), scores, len(origins)
    # Two complete cycles enable a seasonal hypothesis before CV has enough origins.
    return ("seasonal" if available("seasonal", points) else "mean6"), {}, 0

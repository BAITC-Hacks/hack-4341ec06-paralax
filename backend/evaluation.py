"""Untuned final-three-month holdout against mean6, scored on observed raw sales."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.cli import write
from backend.forecast import month_days, predict, select_model
from backend.planning import history
from backend.validation import Json, validate_input


def evaluate(data: Json) -> Json:
    validate_input(data)
    rows = []
    errors, baseline_errors, total_actual = [], [], 0.0
    for product in data["products"]:
        sku = product["sku"]
        points, _, _, _, _ = history(data, sku)
        if len(points) < 15:
            continue
        train, holdout = points[:-3], points[-3:]
        model, _, _ = select_model(train)
        actual_by_month = {
            p["month"]: p["quantity"] for p in data.get("monthly_history", []) if p["sku"] == sku
        }
        for month, _ in holdout:
            actual = actual_by_month.get(month.isoformat())
            if actual is None:
                continue
            predicted = predict(model, train, month) * month_days(month)
            baseline = predict("mean6", train, month) * month_days(month)
            errors.append(abs(actual - predicted))
            baseline_errors.append(abs(actual - baseline))
            total_actual += actual
            rows.append(
                {
                    "sku": sku,
                    "month": month.isoformat(),
                    "model": model,
                    "actual": actual,
                    "predicted": predicted,
                    "mean6": baseline,
                }
            )
    return {
        "method": "Fixed origin: last 3 months held out; selection within train; raw sales scoring",
        "points": len(rows),
        "model_mae_units": sum(errors) / len(errors) if errors else None,
        "mean6_mae_units": sum(baseline_errors) / len(errors) if errors else None,
        "model_wape": sum(errors) / total_actual if total_actual else None,
        "mean6_wape": sum(baseline_errors) / total_actual if total_actual else None,
        "limitations": [
            "Observed sales are not latent demand during stockouts.",
            "Sample excludes sparse, ambiguous and non-piece SKUs; not representative of all IEK.",
            "Three holdout months do not establish future annual accuracy.",
            "Model selection in production uses later data than this holdout experiment.",
        ],
        "predictions": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(json.loads(args.input.read_text("utf-8")))
    write(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "predictions"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

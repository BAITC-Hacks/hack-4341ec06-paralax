"""Explicitly paid, synthetic-only experiment: 10 explanations + 10 direct forecasts.

Run manually with --run-live. Does not alter production planning or send partner data.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from jsonschema import validate
from openai import OpenAI

from backend.ai import DEFAULT_MODEL, explain
from backend.forecast import month_days, next_month
from backend.planning import plan

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "gpt-benchmark-20260923"
REFERENCE = {
    "stable": {"daily_forecast": 1, "forecast_28d": 28, "safety_stock": 7, "order": 27},
    "trend": {"daily_forecast": 14, "forecast_28d": 392, "safety_stock": 98, "order": 420},
    "seasonal": {"daily_forecast": 2, "forecast_28d": 56, "safety_stock": 14, "order": 50},
    "spike": {"daily_forecast": 1, "forecast_28d": 28, "safety_stock": 7, "order": 30},
    "stockout": {"daily_forecast": 2, "forecast_28d": 56, "safety_stock": 14, "order": 60},
}
IMPORTANT = {
    "stable": {"forecast_during_coverage", "current_stock", "goods_in_transit"},
    "trend": {"trend_multiplier"},
    "seasonal": {"seasonality_multiplier"},
    "spike": {"anomaly_excess_quantity"},
    "stockout": {"regular_daily_demand", "forecast_during_coverage", "goods_in_transit"},
}
FORECAST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "daily_forecast",
        "forecast_28d",
        "safety_stock",
        "recommended_quantity",
        "method",
        "explanation",
        "assumptions",
    ],
    "properties": {
        "daily_forecast": {"type": "number", "minimum": 0},
        "forecast_28d": {"type": "number", "minimum": 0},
        "safety_stock": {"type": "number", "minimum": 0},
        "recommended_quantity": {"type": "integer", "minimum": 0},
        "method": {"type": "string"},
        "explanation": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}
FORECAST_PROMPT = """Ты независимый аналитик закупок. Это изолированный эксперимент
на синтетических данных, не производственный заказ. Оцени регулярный дневной спрос
на январь 2026 и обоснуй выбор метода по истории. Декабрь 2025 завершён.
Подтверждённый stockout означает цензурированные продажи, а не доказанный нулевой спрос.
Подтверждённое неповторяющееся превышение документа учитывай отдельно от регулярного спроса.
Прогноз на горизонт = 28 * дневной прогноз. Страховой запас = 7 * дневной прогноз.
Заказ = max(0, ceil(прогноз + страховой запас - остаток - допустимый транзит)).
Кратность и MOQ не применяются. Транзит уже проверен на попадание в горизонт.
Выбери разумный метод самостоятельно. Укажи допущения, не выдумывай внешние факты.
Верни JSON по схеме; объяснение на русском."""


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def cases() -> dict[str, dict[str, Any]]:
    result = {}
    settings = {
        "stable": (date(2025, 1, 1), [1] * 12, 5, 3),
        "trend": (date(2025, 1, 1), list(range(2, 14)), 70, 0),
        "seasonal": (date(2024, 1, 1), [2, 2, 3, 4, 6, 8, 10, 9, 6, 4, 3, 2] * 2, 20, 0),
        "spike": (date(2025, 7, 1), [1] * 6, 5, 0),
        "stockout": (date(2025, 7, 1), [2] * 5 + [0], 0, 10),
    }
    for name, (month, rates, stock, transit) in settings.items():
        monthly, observation = [], []
        for rate in rates:
            days = month_days(month)
            quantity = rate * days
            excess = 570 if name == "spike" and month == date(2025, 12, 1) else 0
            censored = name == "stockout" and month == date(2025, 12, 1)
            quantity += excess
            monthly.append(
                {
                    "sku": name,
                    "month": month.isoformat(),
                    "quantity": quantity,
                    "opening_stock": 0 if censored else 1000,
                }
            )
            observation.append(
                {
                    "month": month.isoformat(),
                    "calendar_days": days,
                    "observed_sales": quantity,
                    "verified_one_off_excess": excess,
                    "confirmed_stockout_days": days if censored else 0,
                }
            )
            month = next_month(month)
        sales = []
        if name == "spike":
            sales = [
                {
                    "sku": name,
                    "date": f"2025-12-{d:02d}",
                    "document_id": f"synthetic-{d}",
                    "quantity": 571 if d == 31 else 1,
                }
                for d in range(1, 32)
            ]
        planning_input = {
            "data_source": "synthetic",
            "as_of_date": "2026-01-01",
            "warehouse_id": "synthetic",
            "review_period_days": 14,
            "safety_stock_days": 7,
            "suppliers": [{"supplier_id": "S", "name": "Synthetic", "lead_time_days": 14}],
            "products": [
                {
                    "sku": name,
                    "name": f"Synthetic {name}",
                    "category": "test",
                    "supplier_id": "S",
                    "current_stock": stock,
                    "goods_in_transit": transit,
                    "growth_forecast_pct": 0,
                    "stock_as_of_date": "2026-01-01",
                    "unit": "шт",
                    "shipments": [{"quantity": transit, "expected_date": "2026-01-14"}],
                }
            ],
            "sales": sales,
            "monthly_history": monthly,
            "stockouts": [
                {
                    "sku": name,
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-31",
                    "certainty": "confirmed",
                }
            ]
            if name == "stockout"
            else [],
        }
        result[name] = {
            "planning_input": planning_input,
            "forecast_request": {
                "data_source": "synthetic",
                "case_id": name,
                "forecast_month": "2026-01",
                "horizon_days": 28,
                "safety_stock_days": 7,
                "current_stock": stock,
                "eligible_transit": transit,
                "history": observation,
            },
            "algorithm": plan(planning_input)["recommendations"][0],
        }
    return result


class CaptureClient:
    def __init__(self) -> None:
        self.api = OpenAI(base_url="https://api.openai.com/v1", timeout=45, max_retries=0)
        self.responses = self
        self.record: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.record["request"] = copy.deepcopy(kwargs)
        started = time.monotonic()
        try:
            response = self.api.responses.create(**kwargs)
            self.record.update(
                status=response.status,
                model=response.model,
                raw_text=response.output_text,
                usage=response.usage.model_dump() if response.usage else {},
            )
            return response
        except Exception as error:
            self.record.update(
                error_type=type(error).__name__, http_status=getattr(error, "status_code", None)
            )
            raise
        finally:
            self.record["elapsed_seconds"] = round(time.monotonic() - started, 3)


def one_request(case_id: str, case: dict[str, Any], mode: str, repeat: int) -> dict[str, Any]:
    client = CaptureClient()
    row = {"case_id": case_id, "mode": mode, "repeat": repeat}
    try:
        if mode == "explanation":
            original = copy.deepcopy(case["algorithm"])
            response = explain(
                case["algorithm"], data_source="synthetic", model=DEFAULT_MODEL, client=client
            )
            row["response"] = response
            chosen = set(response["evidence_keys"])
            row["checks"] = {
                "no_fallback": not response["fallback"],
                "plan_unchanged": case["algorithm"] == original,
                "important_evidence_present": IMPORTANT[case_id].issubset(chosen),
                "missing_important_evidence": sorted(IMPORTANT[case_id] - chosen),
            }
        else:
            response = client.create(
                model=DEFAULT_MODEL,
                store=False,
                instructions=FORECAST_PROMPT,
                input=json.dumps(case["forecast_request"], ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "experimental_forecast",
                        "strict": True,
                        "schema": FORECAST_SCHEMA,
                    }
                },
                max_output_tokens=1200,
            )
            if response.status != "completed":
                raise ValueError("Incomplete response")
            predicted = json.loads(response.output_text)
            validate(predicted, FORECAST_SCHEMA)
            row["response"] = predicted
            d = predicted["daily_forecast"]
            request = case["forecast_request"]
            recalculated = max(
                0,
                math.ceil(
                    predicted["forecast_28d"]
                    + predicted["safety_stock"]
                    - request["current_stock"]
                    - request["eligible_transit"]
                    - 1e-9
                ),
            )
            row["checks"] = {
                "schema_valid": True,
                "forecast_arithmetic": math.isclose(
                    predicted["forecast_28d"], 28 * d, abs_tol=1e-6
                ),
                "safety_arithmetic": math.isclose(predicted["safety_stock"], 7 * d, abs_tol=1e-6),
                "order_arithmetic": predicted["recommended_quantity"] == recalculated,
                "reference_order_match": predicted["recommended_quantity"]
                == REFERENCE[case_id]["order"],
                "reference_daily_match": math.isclose(
                    d, REFERENCE[case_id]["daily_forecast"], abs_tol=1e-6
                ),
            }
    except Exception as error:
        row["experiment_error_type"] = type(error).__name__
    finally:
        client.api.close()
    row["api"] = client.record
    write(OUTPUT / f"{mode}-{case_id}-{repeat}.json", row)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Authorize exactly 20 API attempts")
    args = parser.parse_args()
    if not args.run_live:
        parser.error("This paid experiment requires --run-live")
    if (OUTPUT / "results.json").exists():
        raise SystemExit("Results already exist; do not silently spend on another run.")
    load_dotenv(ROOT / ".env", override=False)
    samples = cases()
    write(OUTPUT / "cases.json", samples)
    write(
        OUTPUT / "reference.json",
        {
            "source": "Root policy independent of API responses; not observed future ground truth",
            "policy": "stable; linear trend; January season; remove excess; censor stockout",
            "predictions": REFERENCE,
        },
    )
    tasks = [
        (name, case, mode, repeat)
        for name, case in samples.items()
        for mode in ("explanation", "forecast")
        for repeat in (1, 2)
    ]
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(one_request, *task) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                json.dumps(
                    {
                        "completed": len(results),
                        "of": 20,
                        "case": result["case_id"],
                        "mode": result["mode"],
                        "repeat": result["repeat"],
                        "status": result["api"].get("status", "error"),
                    }
                ),
                flush=True,
            )
    results.sort(key=lambda r: (r["case_id"], r["mode"], r["repeat"]))
    write(OUTPUT / "results.json", results)


if __name__ == "__main__":
    main()

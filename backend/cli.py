"""Local JSON interface for the forecasting workstream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from backend.ai import explain
from backend.importers.iek import import_iek
from backend.planning import plan
from backend.validation import Json


def write(path: Path, data: Json) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Normalized JSON")
    source.add_argument("--data-dir", type=Path, help="Directory containing IEK workbooks")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--lead-time-days", type=int, default=14)
    parser.add_argument("--review-period-days", type=int, default=14)
    parser.add_argument("--safety-stock-days", type=int, default=7)
    parser.add_argument("--explain-sku", help="Synthetic data only; separate explanation JSON")
    args = parser.parse_args()
    if args.data_dir:
        data, audit = import_iek(
            args.data_dir,
            limit=args.limit,
            lead_time_days=args.lead_time_days,
            review_period_days=args.review_period_days,
            safety_stock_days=args.safety_stock_days,
        )
        write(args.output.with_suffix(".input.json"), data)
        write(args.output.with_suffix(".audit.json"), audit)
    else:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    result = plan(data)
    write(args.output, result)
    if args.explain_sku:
        row = next(r for r in result["recommendations"] if r["sku"] == args.explain_sku)
        write(
            args.output.with_suffix(".explanation.json"),
            explain(row, data_source=result["data_source"]),
        )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "recommendations": len(result["recommendations"]),
                "status": result["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

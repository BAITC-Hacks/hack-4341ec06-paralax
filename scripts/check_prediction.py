"""Five synthetic acceptance cases with real OpenAI calls; fallback is a failure."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from dotenv import load_dotenv

from backend.ai import explain, required_evidence
from backend.planning import plan
from scripts.benchmark_openai import REFERENCE, cases

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    results = []
    for name, case in cases().items():
        row = plan(case["planning_input"])["recommendations"][0]
        original = copy.deepcopy(row)
        explanation = explain(row, data_source="synthetic")
        passed = (
            not explanation["fallback"]
            and row == original
            and row["recommended_quantity"] == REFERENCE[name]["order"]
            and set(required_evidence(row)) <= set(explanation["evidence_keys"])
        )
        results.append({"case": name, "passed": passed, "explanation": explanation, "row": row})
        print(
            json.dumps(
                {
                    "case": name,
                    "passed": passed,
                    "model": explanation["model"],
                    "fallback_reason": explanation["fallback_reason"],
                }
            )
        )
    output = ROOT / "outputs" / "mvp-live-check.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

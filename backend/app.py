"""HTTP boundary for planning runs, manual review, explanations and CSV export."""

from __future__ import annotations

import csv
import importlib
import importlib.util
import io
import json
import logging
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.explanations import Explainer, explain_recommendation
from backend.store import RunNotFound, RunStore
from backend.validation import (
    validate_planning_input,
    validate_planning_result,
    validate_result_against_input,
)
from backend.workflow import RecommendationNotFound, RunStateError, approve, select_quantity

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
Planner = Callable[[dict[str, Any]], dict[str, Any]]


class SelectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_quantity: Annotated[StrictInt, Field(ge=0)]


def _optional_service(module_name: str, function_name: str) -> Callable[..., Any] | None:
    if importlib.util.find_spec(module_name) is None:
        return None
    service = getattr(importlib.import_module(module_name), function_name, None)
    if service is None:
        logger.warning("%s.%s is not available yet", module_name, function_name)
        return None
    if not callable(service):
        raise RuntimeError(f"{module_name}.{function_name} must be callable")
    return cast(Callable[..., Any], service)


def _new_run(result: dict[str, Any]) -> dict[str, Any]:
    fresh = deepcopy(result)
    fresh["run_id"] = uuid4().hex
    fresh["status"] = "draft"
    issues = validate_planning_result(fresh)
    if issues:
        logger.error("Planner returned invalid result: %s", issues)
        raise HTTPException(status_code=500, detail={"code": "invalid_planner_result"})
    return fresh


def _csv_safe(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _export_csv(run: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "supplier_id",
            "supplier_name",
            "sku",
            "name",
            "recommended_quantity",
            "selected_quantity",
            "status",
            "as_of_date",
        ]
    )
    for row in sorted(run["recommendations"], key=lambda item: (item["supplier_id"], item["sku"])):
        writer.writerow(
            [
                _csv_safe(row["supplier_id"]),
                _csv_safe(row["supplier_name"]),
                _csv_safe(row["sku"]),
                _csv_safe(row["name"]),
                row["recommended_quantity"],
                row["selected_quantity"],
                run["status"],
                run["as_of_date"],
            ]
        )
    return output.getvalue()


def create_app(
    planner: Planner | None = None,
    explainer: Explainer | None = None,
    store: RunStore | None = None,
) -> FastAPI:
    """Create a testable API; absent team modules are discovered on startup."""
    selected_planner = planner or cast(
        Planner | None, _optional_service("backend.planning", "plan")
    )
    # The data module's explanation has a separate contract and still needs an HTTP adapter.
    selected_explainer = explainer
    runs = store or RunStore()
    application = FastAPI(title="Paralax Procurement API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )

    def get_run(run_id: str) -> dict[str, Any]:
        try:
            return runs.get(run_id)
        except RunNotFound as error:
            raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from error

    def get_row(run: dict[str, Any], sku: str) -> dict[str, Any]:
        for row in run["recommendations"]:
            if row["sku"] == sku:
                return cast(dict[str, Any], row)
        raise HTTPException(status_code=404, detail={"code": "sku_not_found"})

    @application.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "planner_ready": selected_planner is not None,
            "ai_ready": selected_explainer is not None,
        }

    @application.get("/api/demo/planning-input")
    def demo_input() -> dict[str, Any]:
        path = ROOT / "fixtures" / "planning-input.sample.json"
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    @application.post("/api/demo/planning-runs", status_code=201)
    def demo_run() -> dict[str, Any]:
        path = ROOT / "fixtures" / "planning-result.demo.json"
        fixture = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        return runs.create(_new_run(fixture))

    @application.post("/api/planning-runs", status_code=201)
    def create_run(payload: dict[str, Any]) -> dict[str, Any]:
        issues = validate_planning_input(payload)
        if issues:
            raise HTTPException(status_code=422, detail={"errors": issues})
        if selected_planner is None:
            raise HTTPException(status_code=503, detail={"code": "planner_not_ready"})
        try:
            calculated = selected_planner(deepcopy(payload))
        except ValueError as error:
            raise HTTPException(
                status_code=422, detail={"errors": [{"field": "$", "reason": str(error)}]}
            ) from error
        except Exception as error:
            logger.exception("Planner failed")
            raise HTTPException(status_code=500, detail={"code": "planner_failed"}) from error
        if not isinstance(calculated, dict):
            raise HTTPException(status_code=500, detail={"code": "invalid_planner_result"})
        calculated = deepcopy(calculated)
        calculated["as_of_date"] = payload["as_of_date"]
        calculated["warehouse_id"] = payload["warehouse_id"]
        calculated["data_source"] = payload["data_source"]
        fresh = _new_run(calculated)
        reference_issues = validate_result_against_input(fresh, payload)
        if reference_issues:
            logger.error("Planner result mismatches input: %s", reference_issues)
            raise HTTPException(status_code=500, detail={"code": "invalid_planner_result"})
        return runs.create(fresh)

    @application.get("/api/planning-runs/{run_id}")
    def read_run(run_id: str) -> dict[str, Any]:
        return get_run(run_id)

    @application.patch("/api/planning-runs/{run_id}/recommendations/{sku}")
    def edit_row(run_id: str, sku: str, body: SelectionBody) -> dict[str, Any]:
        try:
            return runs.update(
                run_id, lambda run: select_quantity(run, sku, body.selected_quantity)
            )
        except RunNotFound as error:
            raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from error
        except RecommendationNotFound as error:
            raise HTTPException(status_code=404, detail={"code": "sku_not_found"}) from error
        except RunStateError as error:
            raise HTTPException(status_code=409, detail={"code": "run_approved"}) from error

    @application.post("/api/planning-runs/{run_id}/approve")
    def approve_run(run_id: str) -> dict[str, Any]:
        try:
            return runs.update(run_id, approve)
        except RunNotFound as error:
            raise HTTPException(status_code=404, detail={"code": "run_not_found"}) from error

    @application.post("/api/planning-runs/{run_id}/recommendations/{sku}/explanation")
    def explain_row(run_id: str, sku: str) -> dict[str, Any]:
        row = get_row(get_run(run_id), sku)
        return explain_recommendation(row, selected_explainer)

    @application.get("/api/planning-runs/{run_id}/export")
    def export_run(run_id: str) -> Response:
        run = get_run(run_id)
        return Response(
            content="\ufeff" + _export_csv(run),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="planning-{run_id}.csv"'},
        )

    return application


app = create_app()

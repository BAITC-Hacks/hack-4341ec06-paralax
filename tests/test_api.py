"""Smoke tests for the human review flow and the data-team integration seam."""

from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.explanations import fallback_explanation

ROOT = Path(__file__).resolve().parents[1]


def fixture(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def test_demo_review_approval_explanation_and_export(monkeypatch: Any) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with TestClient(create_app()) as client:
        response = client.post("/api/demo/planning-runs")
        assert response.status_code == 201
        draft = response.json()
        run_id = draft["run_id"]
        assert draft["data_source"] == "synthetic"
        assert draft["status"] == "draft"

        edited = client.patch(
            f"/api/planning-runs/{run_id}/recommendations/CABLE-01",
            json={"selected_quantity": 31},
        )
        assert edited.status_code == 200
        row = next(item for item in edited.json()["recommendations"] if item["sku"] == "CABLE-01")
        assert row["recommended_quantity"] == 25
        assert row["selected_quantity"] == 31

        explained = client.post(f"/api/planning-runs/{run_id}/recommendations/CABLE-01/explanation")
        assert explained.status_code == 200
        assert explained.json()["source"] == "fallback"

        approved = client.post(f"/api/planning-runs/{run_id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert client.post(f"/api/planning-runs/{run_id}/approve").json() == approved.json()
        assert (
            client.patch(
                f"/api/planning-runs/{run_id}/recommendations/CABLE-01",
                json={"selected_quantity": 1},
            ).status_code
            == 409
        )

        exported = client.get(f"/api/planning-runs/{run_id}/export")
        assert exported.status_code == 200
        rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        cable = next(item for item in rows if item["sku"] == "CABLE-01")
        assert cable["recommended_quantity"] == "25"
        assert cable["selected_quantity"] == "31"
        assert cable["status"] == "approved"


def test_default_http_explanation_uses_backend_ai(monkeypatch: Any) -> None:
    received: list[str] = []

    def fake_explain(row: dict[str, Any], *, data_source: str) -> dict[str, Any]:
        received.append(data_source)
        return {
            "summary": f"Заказ {row['recommended_quantity']} шт.",
            "drivers": ["Учтён прогноз."],
            "risk": "Проверьте остаток.",
            "review_question": "Подтверждаете?",
            "evidence_keys": ["forecast_during_coverage"],
            "fallback": False,
        }

    monkeypatch.setattr("backend.ai.explain", fake_explain)
    with TestClient(create_app()) as client:
        run = client.post("/api/demo/planning-runs").json()
        response = client.post(
            f"/api/planning-runs/{run['run_id']}/recommendations/CABLE-01/explanation"
        )
        assert response.status_code == 200
        assert response.json()["source"] == "openai"
        assert received == ["synthetic"]


def test_real_run_validates_input_and_uses_injected_planner() -> None:
    received: list[dict] = []

    def planner(payload: dict) -> dict:
        received.append(deepcopy(payload))
        return fixture("planning-result.sample.json")

    with TestClient(create_app(planner=planner)) as client:
        payload = fixture("planning-input.sample.json")
        created = client.post("/api/planning-runs", json=payload)
        assert created.status_code == 201
        assert received == [payload]
        assert client.get(f"/api/planning-runs/{created.json()['run_id']}").json() == created.json()

        invalid = deepcopy(payload)
        del invalid["sales"][0]["document_id"]
        rejected = client.post("/api/planning-runs", json=invalid)
        assert rejected.status_code == 422
        assert any("sales.0" in issue["field"] for issue in rejected.json()["detail"]["errors"])
        assert len(received) == 1

        wrong_supplier = deepcopy(payload)
        wrong_supplier["products"][0]["supplier_id"] = "unknown"
        rejected_reference = client.post("/api/planning-runs", json=wrong_supplier)
        assert rejected_reference.status_code == 422
        assert any(
            issue["reason"] == "unknown supplier"
            for issue in rejected_reference.json()["detail"]["errors"]
        )


def test_http_uses_integrated_planner_and_eligible_transit() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["planner_ready"] is True
        payload = fixture("planning-input.sample.json")
        payload["products"][0]["shipments"] = [
            {"quantity": payload["products"][0]["goods_in_transit"], "expected_date": "2027-01-01"}
        ]
        created = client.post("/api/planning-runs", json=payload)
        assert created.status_code == 201, created.text
        result = created.json()
        row = next(item for item in result["recommendations"] if item["sku"] == "CABLE-01")
        assert row["factors"]["goods_in_transit"] == 0
        assert row["factors"]["excluded_late_transit"] == payload["products"][0]["goods_in_transit"]
        assert client.get(f"/api/planning-runs/{result['run_id']}").json() == result
        assert client.get(f"/api/planning-runs/{result['run_id']}/export").status_code == 200


def test_iek_route_uses_prepared_normalized_input(tmp_path: Path, monkeypatch) -> None:
    prepared = tmp_path / "outputs" / "iek-planning-result.input.json"
    prepared.parent.mkdir()
    payload = fixture("planning-input.sample.json")
    payload["data_source"] = "partner_excel"
    prepared.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("backend.app.ROOT", tmp_path)

    with TestClient(create_app()) as client:
        response = client.post("/api/iek/planning-runs")
        assert response.status_code == 201, response.text
        assert response.json()["data_source"] == "partner_excel"
        assert len(response.json()["recommendations"]) == len(payload["products"])


def test_fallback_explanation_formats_computed_decimal_values() -> None:
    row = fixture("planning-result.sample.json")["recommendations"][0]
    row["factors"]["forecast_during_coverage"] = 0.1 + 0.2
    explanation = fallback_explanation(row)
    assert "0.30" in explanation["drivers"][0]
    assert "000000000000" not in explanation["drivers"][0]


def test_untrusted_ai_output_falls_back_without_changing_order() -> None:
    def untrusted_explainer(row: dict) -> dict:
        return {
            "summary": "Нужно заказать 9999 шт.",
            "drivers": ["Спрос высокий"],
            "risk": "Проверить остаток",
            "review_question": "Подтвердить?",
            "evidence_keys": ["nonexistent_factor"],
        }

    with TestClient(create_app(explainer=untrusted_explainer)) as client:
        draft = client.post("/api/demo/planning-runs").json()
        run_id = draft["run_id"]
        response = client.post(f"/api/planning-runs/{run_id}/recommendations/CABLE-01/explanation")
        assert response.status_code == 200
        assert response.json()["source"] == "fallback"
        current = client.get(f"/api/planning-runs/{run_id}").json()
        assert current["recommendations"][0]["recommended_quantity"] == 25


def test_valid_ai_explanation_cannot_mutate_saved_recommendation() -> None:
    def explainer(row: dict) -> dict:
        row["recommended_quantity"] = 9999
        return {
            "summary": "Рекомендация основана на доступных факторах.",
            "drivers": ["Учтён текущий остаток."],
            "risk": "Проверьте дату остатка.",
            "review_question": "Подтверждаете остаток?",
            "evidence_keys": ["current_stock"],
        }

    with TestClient(create_app(explainer=explainer)) as client:
        draft = client.post("/api/demo/planning-runs").json()
        run_id = draft["run_id"]
        response = client.post(f"/api/planning-runs/{run_id}/recommendations/CABLE-01/explanation")
        assert response.status_code == 200
        assert response.json()["source"] == "openai"
        current = client.get(f"/api/planning-runs/{run_id}").json()
        assert current["recommendations"][0]["recommended_quantity"] == 25


def test_csv_escapes_spreadsheet_formula_in_product_name() -> None:
    def planner(payload: dict) -> dict:
        result = fixture("planning-result.sample.json")
        result["recommendations"][0]["name"] = '=HYPERLINK("https://example.com")'
        return result

    with TestClient(create_app(planner=planner)) as client:
        created = client.post("/api/planning-runs", json=fixture("planning-input.sample.json"))
        assert created.status_code == 201
        exported = client.get(f"/api/planning-runs/{created.json()['run_id']}/export")
        rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        cable = next(item for item in rows if item["sku"] == "CABLE-01")
        assert cable["name"].startswith("'=")

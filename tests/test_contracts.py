"""Contract and fixture checks that run before application code exists."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from backend.explanations import fallback_explanation

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "fixtures"


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["planning-input", "planning-result", "explanation"])
def test_schema_is_valid(name: str) -> None:
    schema = load_json(CONTRACTS / f"{name}.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("schema_name", "fixture_name"),
    [
        ("planning-input", "planning-input.sample"),
        ("planning-result", "planning-result.sample"),
        ("planning-result", "planning-result.demo"),
    ],
)
def test_fixture_matches_schema(schema_name: str, fixture_name: str) -> None:
    schema = load_json(CONTRACTS / f"{schema_name}.schema.json")
    fixture = load_json(FIXTURES / f"{fixture_name}.json")
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        fixture
    )


def test_input_rejects_negative_stock() -> None:
    schema = load_json(CONTRACTS / "planning-input.schema.json")
    fixture = load_json(FIXTURES / "planning-input.sample.json")
    products = fixture["products"]
    assert isinstance(products, list)
    products[0]["current_stock"] = -1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(fixture, schema)


def test_input_allows_missing_price_but_requires_document_id() -> None:
    schema = load_json(CONTRACTS / "planning-input.schema.json")
    fixture = load_json(FIXTURES / "planning-input.sample.json")
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    validator.validate(fixture)
    sales = fixture["sales"]
    assert isinstance(sales, list)
    del sales[0]["document_id"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(fixture)


def test_fallback_explanation_matches_contract() -> None:
    schema = load_json(CONTRACTS / "explanation.schema.json")
    result = load_json(FIXTURES / "planning-result.demo.json")
    recommendations = result["recommendations"]
    assert isinstance(recommendations, list)
    explanation = fallback_explanation(recommendations[0])
    jsonschema.Draft202012Validator(schema).validate(explanation)

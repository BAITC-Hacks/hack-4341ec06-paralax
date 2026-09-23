"""Contract and fixture checks that run before application code exists."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "fixtures"


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["planning-input", "planning-result"])
def test_schema_is_valid(name: str) -> None:
    schema = load_json(CONTRACTS / f"{name}.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", ["planning-input", "planning-result"])
def test_fixture_matches_schema(name: str) -> None:
    schema = load_json(CONTRACTS / f"{name}.schema.json")
    fixture = load_json(FIXTURES / f"{name}.sample.json")
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

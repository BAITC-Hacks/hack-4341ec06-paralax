"""Apply explicit user-entered balances to the Stage-5 source snapshot.

The output is a local scenario, never a modified partner workbook. Missing
values stay missing unless the user supplies them. Each replaced evidence
record keeps the original source evidence next to the user entry.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping

from deficit import validate_date, valid_quantity

SOURCE_FILE = Path(".analysis/balances/source-snapshot.jsonl")
OUTPUT_FILE = Path(".analysis/balances/user-input.jsonl")
BRANDS = {"IEK", "Systeme Electric"}
BalanceKey = tuple[str, str]


def require_as_of_date(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("as_of_date must be YYYY-MM-DD")
    validate_date(value, "as_of_date")
    return value


def require_quantity(value: object, field: str) -> int | float:
    if value is None:
        raise ValueError(f"{field} quantity must be explicitly numeric")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError(f"{field} quantity must be nonnegative")
        if value > 2**53 - 1:
            raise ValueError(f"{field} quantity exceeds exact numeric range")
    valid_quantity(value, field)
    return value


def parse_entries(entries: Iterable[str], field: str) -> dict[BalanceKey, int | float]:
    """Parse repeated ``BRAND:SKU=QUANTITY`` arguments without merging repeats."""
    result: dict[BalanceKey, int | float] = {}
    for entry in entries:
        name, separator, amount_text = entry.rpartition("=")
        brand, brand_separator, sku = name.partition(":")
        if not separator or not brand_separator or brand not in BRANDS or not sku.strip() \
                or brand != brand.strip() or sku != sku.strip():
            raise ValueError(
                f"Invalid {field} entry {entry!r}; use 'IEK:SKU=QUANTITY' or "
                "'Systeme Electric:SKU=QUANTITY'"
            )
        key = (brand, sku)
        if key in result:
            raise ValueError(f"Duplicate {field} entry for {brand} / {sku}")
        if not amount_text or amount_text != amount_text.strip():
            raise ValueError(f"Invalid {field} quantity for {brand} / {sku}")
        try:
            quantity = json.loads(amount_text)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid {field} quantity for {brand} / {sku}") from error
        result[key] = require_quantity(quantity, field)
    return result


def user_evidence(quantity: int | float, as_of_date: str, field: str,
                  brand: str, sku: str) -> dict:
    """A user-attested current value, clearly distinct from workbook evidence."""
    return {
        "quantity": quantity,
        "quality": "confirmed_current",
        "as_of_date": as_of_date,
        "basis": "user_entered_attested",
        "source_refs": [{
            "source": "user_input",
            "field": field,
            "brand": brand,
            "sku": sku,
            "as_of_date": as_of_date,
        }],
        "scope_note": (
            "Значение и дата введены пользователем; не сверены автоматически с 1С или складом. "
            "Проверьте охват складов и исключите двойной учёт товара в пути."
        ),
        "verification": "user_attested_not_independently_verified",
    }


def apply_overrides(record: dict, as_of_date: str,
                    stock_overrides: Mapping[BalanceKey, int | float],
                    transit_overrides: Mapping[BalanceKey, int | float]) -> dict:
    """Return a new balance row, preserving every workbook-derived field."""
    require_as_of_date(as_of_date)
    key = (record["brand"], record["sku"])
    updated = copy.deepcopy(record)
    updates = (
        ("current_stock", "source_current_stock", stock_overrides, "user_entered_current_stock"),
        ("goods_in_transit", "source_goods_in_transit", transit_overrides,
         "user_entered_goods_in_transit"),
    )
    for field, original_field, overrides, note in updates:
        if key not in overrides:
            continue
        quantity = overrides[key]
        require_quantity(quantity, field)
        if original_field not in updated:
            updated[original_field] = copy.deepcopy(record.get(field))
        updated[field] = user_evidence(quantity, as_of_date, field, *key)
        updated.setdefault("notes", []).append(note)
    return updated


def apply_stock_inputs(source_path: Path, output_path: Path, as_of_date: str,
                       stock_overrides: Mapping[BalanceKey, int | float],
                       transit_overrides: Mapping[BalanceKey, int | float]) -> dict[str, int]:
    """Write an atomic local scenario, rejecting unknown or repeated SKU keys."""
    require_as_of_date(as_of_date)
    if not stock_overrides and not transit_overrides:
        raise ValueError("Supply at least one --stock or --transit entry")
    if source_path.resolve() == output_path.resolve():
        raise ValueError("Output must differ from the source balance file")
    if not source_path.is_file():
        raise ValueError(f"Source balance file does not exist: {source_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[BalanceKey] = set()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=output_path.parent,
            prefix="user-input-", suffix=".tmp", delete=False,
        ) as destination:
            temporary = Path(destination.name)
            with source_path.open(encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    record = json.loads(line)
                    key = (record["brand"], record["sku"])
                    if key in seen:
                        raise ValueError(f"Duplicate source balance SKU at line {line_number}: {key}")
                    seen.add(key)
                    updated = apply_overrides(
                        record, as_of_date, stock_overrides, transit_overrides)
                    destination.write(json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "\n")
        unknown = (set(stock_overrides) | set(transit_overrides)) - seen
        if unknown:
            label = ", ".join(f"{brand} / {sku}" for brand, sku in sorted(unknown))
            raise ValueError(f"User input has SKUs absent from source balances: {label}")
        os.replace(temporary, output_path)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return {"rows": len(seen), "stock_entries": len(stock_overrides),
            "transit_entries": len(transit_overrides)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD date attested by user")
    parser.add_argument("--stock", action="append", default=[], metavar="BRAND:SKU=QUANTITY",
                        help="current stock entered by user; repeat for several SKUs")
    parser.add_argument("--transit", action="append", default=[], metavar="BRAND:SKU=QUANTITY",
                        help="optional user confirmation of goods in transit")
    args = parser.parse_args()
    try:
        stock = parse_entries(args.stock, "current_stock")
        transit = parse_entries(args.transit, "goods_in_transit")
        result = apply_stock_inputs(args.source, args.output, args.as_of_date, stock, transit)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f"User-input balance scenario: {args.output}")
    print(f"Rows: {result['rows']}; user stock: {result['stock_entries']}; "
          f"user transit: {result['transit_entries']}")
    print("Values are user-attested and have not been independently verified.")


if __name__ == "__main__":
    main()

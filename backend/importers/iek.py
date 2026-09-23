"""Read the four supplied IEK exports. Never infer missing stock as zero."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from backend.validation import Json, integer, validate_input

FILES = {
    "monthly_sales": "Ежемесячные продажи в количественном выражении за последние 2 года.xlsx",
    "monthly_stock": "Ежемесячные остатки продукции за последние 2 года  ИЭК.xlsx",
    "documents": "Динамика продаж_2025-2026.xlsx",
    "transit": "Путь ИЭК 22.09.2026.xlsx",
}
MONTHS = (
    "янв.",
    "февр.",
    "март",
    "апр.",
    "май",
    "июнь",
    "июль",
    "авг.",
    "сент.",
    "окт.",
    "нояб.",
    "дек.",
)


def read_rows(path: Path) -> list[tuple[Any, ...]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return list(workbook.worksheets[0].values)
    finally:
        workbook.close()


def month_columns(header: tuple[Any, ...]) -> dict[date, int]:
    result = {}
    for i, value in enumerate(header):
        if not isinstance(value, str):
            continue
        parts = value.split()
        if len(parts) == 2 and parts[0] in MONTHS and parts[1].isdigit():
            result[date(int(parts[1]), MONTHS.index(parts[0]) + 1, 1)] = i
    if not result:
        raise ValueError("No Russian month/year headers found")
    return result


def keyed(rows: list[tuple[Any, ...]], start: int, col: int) -> dict[str, tuple[Any, ...]]:
    result = {}
    for row in rows[start:]:
        if row[col] is None or str(row[col]).strip() == "Итого":
            continue
        sku = str(row[col]).strip()
        if sku in result:
            raise ValueError(f"Duplicate SKU in workbook: {sku}")
        result[sku] = row
    return result


def import_iek(
    data_dir: Path,
    *,
    limit: int = 50,
    lead_time_days: int = 14,
    review_period_days: int = 14,
    safety_stock_days: int = 7,
) -> tuple[Json, Json]:
    if limit < 1:
        raise ValueError("limit must be positive")
    folder = data_dir / "IEK"
    paths = {role: folder / name for role, name in FILES.items()}
    for path in paths.values():
        if not path.is_file():
            raise ValueError(f"Required workbook missing: {path}")
    monthly_rows = read_rows(paths["monthly_sales"])
    stock_rows = read_rows(paths["monthly_stock"])
    transit_rows = read_rows(paths["transit"])
    if monthly_rows[0][:2] != ("Номенклатура", "Номенклатура.Код"):
        raise ValueError("Monthly sales headers changed")
    if stock_rows[0][:3] != ("Номенклатура", "Ед.", "Номенклатура.Код"):
        raise ValueError("Monthly stock headers changed")
    if not all(stock_rows[2][i] == "нач. остаток" for i in month_columns(stock_rows[0]).values()):
        raise ValueError("Expected opening, not closing, stock")
    monthly = keyed(monthly_rows, 2, 1)
    stocks = keyed(stock_rows, 3, 2)
    transit_counts = Counter(str(row[0]).strip() for row in transit_rows[1:] if row[0])
    ambiguous_transit = sorted(k for k, n in transit_counts.items() if n > 1)
    transit = keyed(
        [transit_rows[0]]
        + [row for row in transit_rows[1:] if str(row[0]).strip() not in ambiguous_transit],
        1,
        0,
    )
    columns = month_columns(monthly_rows[0])
    stock_columns = month_columns(stock_rows[0])
    as_of = date(2026, 9, 22)  # Snapshot encoded in the explicitly supported filename.
    stock_month = as_of.replace(day=1)
    complete = sorted(m for m in columns if m < stock_month)
    if stock_month not in stock_columns:
        raise ValueError("September opening stock is missing")
    eta_columns: dict[int, str] = {}
    for i, heading in enumerate(transit_rows[0][3:], 3):
        match = re.search(r"поступление до (\d{2}\.\d{2}\.\d{4})", str(heading))
        if not match:
            raise ValueError(f"Missing ETA in transit column {i + 1}")
        eta_columns[i] = datetime.strptime(match[1], "%d.%m.%Y").date().isoformat()
    excluded: Counter[str] = Counter()
    candidates = []
    for sku in sorted(monthly):
        if sku not in stocks or sku not in transit:
            excluded["missing_stock_or_transit_row"] += 1
            continue
        stock = stocks[sku]
        if stock[1] != "шт":
            excluded["unit_requires_conversion"] += 1
            continue
        if stock[stock_columns[stock_month]] is None:
            excluded["unknown_current_stock"] += 1
            continue
        values = [monthly[sku][columns[m]] for m in complete]
        if sum(v is not None for v in values) < 24 or any(v is None for v in values[-6:]):
            excluded["insufficient_observed_history"] += 1
            continue
        try:
            integer(stock[stock_columns[stock_month]], sku)
            for v in values:
                if v is not None:
                    integer(v, sku)
            for m in complete:
                v = stock[stock_columns[m]] if m in stock_columns else None
                if v is not None:
                    integer(v, sku)
            for i in eta_columns:
                if transit[sku][i] is not None:
                    integer(transit[sku][i], sku)
        except ValueError:
            excluded["invalid_or_negative_quantity"] += 1
            continue
        candidates.append(sku)
    selected = set(candidates)
    if not selected:
        raise ValueError("No eligible IEK SKUs; inspect source coverage and units")
    documents = read_rows(paths["documents"])
    if documents[0] != (
        "Дата",
        "Номер",
        "Документ",
        "Код",
        "Номенклатура",
        "Ед.",
        "Склад",
        "Количество",
    ):
        raise ValueError("Document export headers changed")
    sales_by_key: dict[tuple[str, str, str, str], int] = defaultdict(int)
    negative_rows: list[Json] = []
    duplicate_rows = 0
    seen: set[tuple[Any, ...]] = set()
    warehouses: set[str] = set()
    bad_units: set[str] = set()
    invalid_documents: list[Json] = []
    bad_document_skus: set[str] = set()
    for row_number, row in enumerate(documents[1:], 2):
        sku = str(row[3]).strip()
        if sku not in selected:
            continue
        if row in seen:
            duplicate_rows += 1
            bad_document_skus.add(sku)
            invalid_documents.append({"row": row_number, "sku": sku, "reason": "duplicate"})
            continue
        seen.add(row)
        if row[5] != stocks[sku][1]:
            bad_units.add(sku)
            continue
        stamp = (
            row[0]
            if isinstance(row[0], datetime)
            else datetime.strptime(str(row[0]), "%d.%m.%Y %H:%M:%S")
        ).date()
        if stamp > as_of:
            raise ValueError("Future document in snapshot")
        if not isinstance(row[7], (int, float)):
            bad_document_skus.add(sku)
            invalid_documents.append({"row": row_number, "sku": sku, "reason": "unknown_quantity"})
            continue
        if row[7] < 0:
            negative_rows.append({"row": row_number, "sku": sku, "quantity": row[7]})
            continue
        quantity = integer(row[7], f"document row {row_number}")
        if not row[1] or not row[6]:
            raise ValueError(f"Missing document ID or warehouse at row {row_number}")
        if not str(row[2]).startswith("Расходная"):
            raise ValueError("Unrecognized positive document type")
        if quantity and stamp >= min(complete) and stamp < stock_month:
            key = (sku, stamp.isoformat(), str(row[1]), str(row[6]))
            sales_by_key[key] += quantity
            warehouses.add(str(row[6]))
    observed_skus = {key[0] for key in sales_by_key}
    selected = set(
        [
            sku
            for sku in candidates
            if sku not in bad_units | bad_document_skus and sku in observed_skus
        ][:limit]
    )
    if not selected:
        raise ValueError("No SKU with consistent document data")
    sales_by_key = {key: qty for key, qty in sales_by_key.items() if key[0] in selected}
    products, history = [], []
    for sku in sorted(selected):
        stock = stocks[sku]
        shipments: list[Json] = [
            {"quantity": integer(transit[sku][i], sku), "expected_date": eta}
            for i, eta in eta_columns.items()
            if transit[sku][i] is not None
        ]
        quality = [
            "Охват складов месячных остатков и продаж не подтверждён.",
            "MOQ и кратность не применены: смысл и единицы не подтверждены.",
        ]
        if any(item["sku"] == sku for item in negative_rows):
            quality.append("В документах есть отрицательные корректировки; см. локальный аудит.")
        products.append(
            {
                "sku": sku,
                "name": str(monthly[sku][0]).strip(),
                "category": "Не классифицировано",
                "supplier_id": "IEK",
                "current_stock": integer(stock[stock_columns[stock_month]], sku),
                "goods_in_transit": sum(s["quantity"] for s in shipments),
                "growth_forecast_pct": 0,
                "unit": "шт",
                "stock_as_of_date": stock_month.isoformat(),
                "stock_source": f"data/IEK/{FILES['monthly_stock']}; нач. остаток",
                "stock_scope": "supplier_export_scope_unconfirmed",
                "shipments": shipments,
                "quality_warnings": quality,
            }
        )
        for m in complete:
            history.append(
                {
                    "sku": sku,
                    "month": m.isoformat(),
                    "quantity": monthly[sku][columns[m]],
                    "opening_stock": stock[stock_columns[m]] if m in stock_columns else None,
                }
            )
    data: Json = {
        "schema_version": "0.2.0",
        "as_of_date": as_of.isoformat(),
        "warehouse_id": "IEK-export-scope-unconfirmed",
        "data_source": "partner_excel",
        "review_period_days": review_period_days,
        "safety_stock_days": safety_stock_days,
        "suppliers": [{"supplier_id": "IEK", "name": "IEK", "lead_time_days": lead_time_days}],
        "products": products,
        "monthly_history": history,
        "stockouts": [],
        "sales": [
            {
                "sku": sku,
                "date": stamp,
                "document_id": document,
                "warehouse_id": warehouse,
                "quantity": qty,
                "unit": "шт",
            }
            for (sku, stamp, document, warehouse), qty in sorted(sales_by_key.items())
        ],
        "source_files": [f"data/IEK/{name}" for name in FILES.values()],
        "assumptions": [
            f"Сценарные параметры: lead={lead_time_days}, review={review_period_days}, "
            f"safety={safety_stock_days} дней; внешний рост=0%.",
            "Остаток на начало 01.09.2026 использован без восстановления поступлений до 22.09.",
            "Охват складов неизвестен; единица транзита предполагается штуками для выбранных SKU.",
            "Пустая ячейка транзита в существующей строке означает отсутствие заказа по колонке.",
            "Пустые продажи/остатки остаются неизвестными; "
            "сентябрьские продажи исключены как неполный месяц.",
            "Дата поступления до из заголовка трактуется как ETA; MOQ/кратность пока не применены.",
        ],
    }
    validate_input(data)
    audit: Json = {
        "source_files": [
            {
                "path": f"data/IEK/{p.name}",
                "role": role,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for role, p in paths.items()
        ],
        "eligible_skus": len(candidates),
        "selected_skus": sorted(selected),
        "selection_rule": "first eligible SKU by code; >=24 months, last6 known, unit шт",
        "excluded_duplicate_transit_skus": ambiguous_transit,
        "excluded_counts": dict(excluded),
        "negative_document_rows": negative_rows,
        "invalid_document_rows": invalid_documents,
        "excluded_document_skus": sorted(bad_units | bad_document_skus),
        "duplicate_document_rows": duplicate_rows,
        "document_warehouses": sorted(warehouses),
        "monthly_history_records": len(history),
        "normalized_documents": len(data["sales"]),
        "unused_files": ["MOQ  ИЭК.xlsx", "Сезонность ИЭК.xlsx", "Systeme electric/*"],
    }
    return data, audit

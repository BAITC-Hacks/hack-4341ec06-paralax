"""Stage 5: traceable stock deficit without MOQ, rounding, or order creation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import tempfile
from datetime import date
from pathlib import Path

from clean_demand import SOURCE_COMMIT

TARGET_FILE = Path(".analysis/target-stock/all-skus.jsonl")
BALANCE_FILE = Path(".analysis/balances/source-snapshot.jsonl")
OUTPUT_DIR = Path(".analysis/deficit")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_quantity(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite nonnegative number or null")
    return float(value)


def validate_date(value: object, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD or null")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD or null") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be YYYY-MM-DD or null")


def calculate_deficit(
    target_record: dict,
    balance_record: dict,
    target_sha256: str = "",
    balance_sha256: str = "",
) -> dict:
    """Subtract only explicitly numeric stock and transit, retaining evidence quality."""
    key = (target_record["brand"], target_record["sku"])
    if key != (balance_record["brand"], balance_record["sku"]):
        raise ValueError("Stage-4 and balance brand/SKU keys differ")
    if (balance_record.get("stage1_sha256") is not None
            and target_record.get("stage1_sha256") != balance_record["stage1_sha256"]):
        raise ValueError("Stage-4 and balance Stage-1 hashes differ")

    target = valid_quantity(target_record.get("target_stock"), "target_stock")
    stock = balance_record.get("current_stock") or {}
    transit = balance_record.get("goods_in_transit") or {}
    stock_quantity = valid_quantity(stock.get("quantity"), "current_stock.quantity")
    transit_quantity = valid_quantity(transit.get("quantity"), "goods_in_transit.quantity")
    for name, item in (("current_stock", stock), ("goods_in_transit", transit)):
        validate_date(item.get("as_of_date"), f"{name}.as_of_date")

    unavailable_reasons = []
    if target is None or target_record.get("status") == "unavailable":
        unavailable_reasons.append("target_stock_unavailable")
    if stock_quantity is None:
        unavailable_reasons.append("current_stock_unavailable")
    if transit_quantity is None:
        unavailable_reasons.append("goods_in_transit_unavailable")

    provisional_reasons = []
    planning_date = target_record.get("planning_date")
    for name, item, quantity in (("current_stock", stock, stock_quantity),
                                 ("goods_in_transit", transit, transit_quantity)):
        if quantity is None:
            continue
        quality = item.get("quality")
        if quality != "confirmed_current":
            provisional_reasons.append(f"{name}:{quality or 'quality_unspecified'}")
        elif item.get("as_of_date") != planning_date:
            provisional_reasons.append(f"{name}:date_differs_from_planning_date")
        elif not item.get("source_refs"):
            provisional_reasons.append(f"{name}:source_ref_missing")

    raw = target - stock_quantity - transit_quantity if not unavailable_reasons else None
    deficit = max(0.0, raw) if raw is not None else None
    status = ("unavailable" if unavailable_reasons else
              "provisional" if provisional_reasons else "calculated")
    return {
        "source_commit": target_record.get("source_commit"),
        "balance_source_commit": balance_record.get("source_commit"),
        "stage1_sha256": target_record.get("stage1_sha256"),
        "stage2_sha256": target_record.get("stage2_sha256"),
        "stage3_sha256": target_record.get("upstream_sha256"),
        "target_sha256": target_sha256,
        "balance_sha256": balance_sha256,
        "brand": key[0], "sku": key[1],
        "name": target_record.get("name", ""), "unit": target_record.get("unit"),
        "planning_date": planning_date,
        "horizon_end_exclusive": target_record.get("horizon_end_exclusive"),
        "target_stock": target,
        "current_stock": stock,
        "goods_in_transit": transit,
        "historical_stock": balance_record.get("historical_stock"),
        "balance_notes": balance_record.get("notes", []),
        "raw_deficit": raw,
        "deficit": deficit,
        "status": status,
        "unavailable_reasons": unavailable_reasons,
        "provisional_reasons": provisional_reasons,
    }


def show(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, (float, int)):
        return f"{value:,.2f}".replace(",", " ")
    return html.escape(str(value))


def quality_label(value: str | None) -> str:
    return {
        "confirmed_current": "Подтверждённый снимок",
        "ambiguous_date": "Дата и охват требуют проверки",
        "historical": "Исторический снимок",
        "missing": "Нет достоверного значения",
        "invalid_source": "Некорректное значение источника",
        "conflict": "Конфликт строк источника",
    }.get(value, "Качество не указано")


def reason_label(value: str) -> str:
    labels = {
        "target_stock_unavailable": "Необходимый запас недоступен",
        "current_stock_unavailable": "Текущий остаток неизвестен",
        "goods_in_transit_unavailable": "Количество товара в пути неизвестно",
        "current_stock:ambiguous_date": "Дата/охват остатка не подтверждены",
        "goods_in_transit:ambiguous_date": "Дата/охват товара в пути не подтверждены",
        "current_stock:historical": "Остаток относится к прошлому снимку",
        "goods_in_transit:historical": "Товар в пути относится к прошлому снимку",
        "current_stock:source_ref_missing": "Нет ссылки на источник остатка",
        "goods_in_transit:source_ref_missing": "Нет ссылки на источник товара в пути",
    }
    if value.startswith("warehouse_scope_differs:"):
        return "Показанные склады не совпадают с полем общего остатка: " + value.split(":", 1)[1]
    return labels.get(value, value)


def render_html(result: dict, path: Path) -> None:
    title = html.escape(f"{result['brand']} / {result['sku']}")
    unit = html.escape(result.get("unit") or "ед.")
    stock = result["current_stock"]
    transit = result["goods_in_transit"]
    historical = result.get("historical_stock")
    status_labels = {"calculated": "Рассчитано", "provisional": "Условный расчёт",
                     "unavailable": "Недоступно"}
    reasons = result["unavailable_reasons"] or result["provisional_reasons"]
    reason_text = ", ".join(reason_label(reason) for reason in reasons) if reasons else "нет"
    source_details = html.escape(json.dumps({
        "current_stock": stock.get("source_refs", []),
        "goods_in_transit": transit.get("source_refs", []),
        "historical_stock": historical.get("source_refs", []) if historical else [],
    }, ensure_ascii=False, indent=2))
    historical_basis = ("на начало месяца" if historical and historical.get("basis") == "beginning_of_month"
                        else historical.get("basis") if historical else "")
    historical_text = (f"Исторический остаток: {show(historical.get('quantity'))} {unit}, "
                       f"{html.escape(historical_basis or '')}, "
                       f"{html.escape(historical.get('as_of_date') or 'дата неизвестна')}. "
                       "В формулу не подставлен."
                       if historical else "")
    evidence_notes = list(dict.fromkeys(
        note for note in (stock.get("scope_note"), transit.get("scope_note"),
                          historical.get("scope_note") if historical else None,
                          *result.get("balance_notes", [])) if note
    ))
    evidence_note_text = "<br>".join(html.escape(reason_label(note)) for note in evidence_notes)
    markup = f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Дефицит — {title}</title><style>
body{{font:15px system-ui;margin:32px;max-width:1050px;color:#173329}}
.cards{{display:flex;gap:14px;flex-wrap:wrap;margin:24px 0}}
.card{{border:1px solid #dce8df;border-radius:9px;padding:16px;min-width:170px}}
.card b{{display:block;font-size:21px;margin-top:8px}}small{{color:#66786b}}
.warning{{background:#fff7e6;padding:15px;border-radius:8px}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f5f7f5;padding:14px}}</style>
<h1>Дефицит: {title}</h1><p>{html.escape(result.get('name') or '')} · {unit} ·
{status_labels[result['status']]}</p>
<p>Дата планирования: {html.escape(result.get('planning_date') or 'не указана')}.
Дефицит = необходимый запас − текущий остаток − товар в пути.</p>
<div class="cards"><div class="card">Необходимый запас<b>{show(result['target_stock'])} {unit}</b>
<small>Этап 4</small></div>
<div class="card">Текущий остаток<b>{show(stock.get('quantity'))} {unit}</b>
<small>{quality_label(stock.get('quality'))}</small></div>
<div class="card">Товар в пути<b>{show(transit.get('quantity'))} {unit}</b>
<small>{quality_label(transit.get('quality'))}</small></div></div>
<p><b>{show(result['target_stock'])} − {show(stock.get('quantity'))} −
{show(transit.get('quantity'))} = {show(result['raw_deficit'])} {unit}</b></p>
<p>Потребность после отсечения отрицательного значения: <b>{show(result['deficit'])} {unit}</b>.
Это ещё не заказ: MOQ, кратность и округление относятся к следующему этапу.</p>
<p class="warning">{html.escape(reason_text)}. {historical_text}
Дата/охват остатков и товара в пути должны быть подтверждены перед реальной закупкой.<br>
{evidence_note_text}</p>
<h2>Ссылки на исходные ячейки</h2><pre>{source_details}</pre>
<small>SHA-256 необходимого запаса: {html.escape(result['target_sha256'])};
SHA-256 файла балансов: {html.escape(result['balance_sha256'])}.
Точные числа и дополнительные примечания находятся в JSON рядом.</small></html>"""
    path.write_text(markup, encoding="utf-8")


def write_csv(result: dict, path: Path) -> None:
    stock, transit = result["current_stock"], result["goods_in_transit"]
    fields = ["brand", "sku", "unit", "target_stock", "current_stock",
              "stock_quality", "stock_as_of_date", "stock_scope_note", "goods_in_transit",
              "transit_quality", "transit_as_of_date", "transit_scope_note",
              "historical_stock", "raw_deficit", "deficit", "status",
              "unavailable_reasons", "provisional_reasons", "balance_notes"]
    row = {
        "brand": result["brand"], "sku": result["sku"], "unit": result["unit"],
        "target_stock": result["target_stock"], "current_stock": stock.get("quantity"),
        "stock_quality": stock.get("quality"), "stock_as_of_date": stock.get("as_of_date"),
        "stock_scope_note": stock.get("scope_note"),
        "goods_in_transit": transit.get("quantity"), "transit_quality": transit.get("quality"),
        "transit_as_of_date": transit.get("as_of_date"),
        "transit_scope_note": transit.get("scope_note"),
        "historical_stock": (result["historical_stock"] or {}).get("quantity"),
        "raw_deficit": result["raw_deficit"], "deficit": result["deficit"],
        "status": result["status"],
        "unavailable_reasons": ";".join(result["unavailable_reasons"]),
        "provisional_reasons": ";".join(result["provisional_reasons"]),
        "balance_notes": ";".join(result["balance_notes"]),
    }
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def load_balances(path: Path) -> dict[tuple[str, str], dict]:
    balances = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            record = json.loads(line)
            key = (record["brand"], record["sku"])
            if key in balances:
                raise ValueError(f"Duplicate balance SKU at line {line_number}: {key}")
            balances[key] = record
    return balances


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET_FILE)
    parser.add_argument("--balances", type=Path, default=BALANCE_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--sku", action="append", help="write focused HTML/CSV/JSON; repeatable")
    parser.add_argument("--brand", choices=("IEK", "Systeme Electric"))
    args = parser.parse_args()
    if args.brand and not args.sku:
        parser.error("--brand requires --sku")
    for path in (args.target, args.balances):
        if not path.is_file():
            parser.error(f"Required input is missing: {path}")
    try:
        balances = load_balances(args.balances)
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))
    target_sha, balance_sha = file_hash(args.target), file_hash(args.balances)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = []
    counts = {"calculated": 0, "provisional": 0, "unavailable": 0}
    seen_keys = set()
    output = args.output_dir / "all-skus.jsonl"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output_dir,
                                         prefix="deficit-", suffix=".tmp", delete=False) as destination:
            temp_path = Path(destination.name)
            with args.target.open(encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    target_record = json.loads(line)
                    key = (target_record["brand"], target_record["sku"])
                    if key in seen_keys:
                        raise ValueError(f"Duplicate Stage-4 SKU at line {line_number}: {key}")
                    seen_keys.add(key)
                    if target_record.get("source_commit") != SOURCE_COMMIT:
                        raise ValueError(f"Invalid Stage-4 source commit at line {line_number}")
                    balance_record = balances.get(key, {
                        "brand": key[0], "sku": key[1],
                        "current_stock": {"quantity": None, "quality": "missing"},
                        "goods_in_transit": {"quantity": None, "quality": "missing"},
                        "notes": ["balance_record_missing"],
                    })
                    try:
                        result = calculate_deficit(target_record, balance_record,
                                                   target_sha, balance_sha)
                    except ValueError as error:
                        raise ValueError(f"{key[0]} / {key[1]}: {error}") from error
                    destination.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts[result["status"]] += 1
                    if (args.sku and key[1] in args.sku
                            and (not args.brand or key[0] == args.brand)):
                        selected.append(result)
        extra_keys = set(balances) - seen_keys
        if extra_keys:
            raise ValueError(f"Balance file has {len(extra_keys)} SKUs absent from Stage 4")
        missing = set(args.sku or []) - {item["sku"] for item in selected}
        if missing:
            raise ValueError(f"SKUs not found: {', '.join(sorted(missing))}")
        os.replace(temp_path, output)
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        parser.error(str(error))

    for result in selected:
        stem = ("iek-" if result["brand"] == "IEK" else "systeme-") + re.sub(
            r"[^A-Za-z0-9_-]", "-", result["sku"])
        (args.output_dir / f"{stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(result, args.output_dir / f"{stem}.csv")
        render_html(result, args.output_dir / f"{stem}.html")
    print(f"Deficit for {sum(counts.values())} SKUs: {output}")
    print("Status:", counts)
    def cli_number(value: object) -> str:
        return "null" if value is None else f"{value:.2f}"
    for result in selected:
        stock = result["current_stock"].get("quantity")
        transit = result["goods_in_transit"].get("quantity")
        print(result["brand"], result["sku"], result["status"],
              f"{cli_number(result['target_stock'])} - {cli_number(stock)} - {cli_number(transit)} "
              f"= {cli_number(result['raw_deficit'])}; deficit {cli_number(result['deficit'])}")


if __name__ == "__main__":
    main()

"""Stage 6: explainable purchase recommendation from Stage 4/5 and source packing rules.

This is an analytical intermediate result, not an approved supplier order.
Unknown stock, transit, target, or a needed packing rule is never replaced by zero.
"""

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
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from clean_demand import SOURCE_COMMIT

TARGET_FILE = Path(".analysis/target-stock/all-skus.jsonl")
DEFICIT_FILE = Path(".analysis/deficit/all-skus.jsonl")
RULES_FILE = Path(".analysis/packing-rules/source-rules.jsonl")
OUTPUT_DIR = Path(".analysis/orders")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nonnegative_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite nonnegative number or null")
    return float(value)


def rule_quantity(rule: dict) -> int | None:
    value = rule.get("quantity")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Packing-rule quantity must be a positive integer or null")
    if value <= 0 or value != int(value):
        raise ValueError("Packing-rule quantity must be a positive integer or null")
    return int(value)


def rounded_order(deficit: float, kind: str, quantity: int) -> int:
    """Convert positive fractional need to whole units, then apply the source rule."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("Packing-rule quantity must be a positive integer")
    if not math.isfinite(deficit) or deficit < 0:
        raise ValueError("Deficit must be finite and nonnegative")
    if deficit <= 0:
        return 0
    # Stage 4/5 use binary floats; remove only sub-nanounit arithmetic noise at
    # a threshold so 20.000000000000004 does not become two packs of 20.
    nearest_integer = round(deficit)
    if nearest_integer > 0 and math.isclose(deficit, nearest_integer, rel_tol=0, abs_tol=1e-9):
        deficit = float(nearest_integer)
    need = Decimal(str(deficit))
    if kind == "multiple":
        nearest_pack = round(deficit / quantity) * quantity
        if nearest_pack > 0 and math.isclose(deficit, nearest_pack, rel_tol=0, abs_tol=1e-9):
            return nearest_pack
        return int((need / Decimal(quantity)).to_integral_value(rounding=ROUND_CEILING)) * quantity
    if kind == "minimum_dispatch":
        return max(int(need.to_integral_value(rounding=ROUND_CEILING)), quantity)
    raise ValueError(f"Unknown packing rule kind: {kind}")


def calculate_order(deficit_record: dict, target_record: dict, rule_record: dict | None,
                    *, deficit_sha256: str = "", rules_sha256: str = "") -> dict:
    key = (deficit_record["brand"], deficit_record["sku"])
    if key != (target_record["brand"], target_record["sku"]):
        raise ValueError("Stage-4 and Stage-5 brand/SKU keys differ")
    if deficit_record.get("source_commit") != target_record.get("source_commit"):
        raise ValueError("Stage-4 and Stage-5 source commits differ")
    if deficit_record.get("planning_date") != target_record.get("planning_date"):
        raise ValueError("Stage-4 and Stage-5 planning dates differ")
    if rule_record is not None:
        if key != (rule_record["brand"], rule_record["sku"]):
            raise ValueError("Packing-rule brand/SKU key differs")
        if rule_record.get("source_commit") != deficit_record.get("source_commit"):
            raise ValueError("Packing-rule source commit differs")

    raw = deficit_record.get("raw_deficit")
    raw = None if raw is None else float(raw)
    if raw is not None and not math.isfinite(raw):
        raise ValueError("raw_deficit must be finite or null")
    deficit = nonnegative_number(deficit_record.get("deficit"), "deficit")
    target_stock = nonnegative_number(target_record.get("target_stock"), "target_stock")
    deficit_target = nonnegative_number(deficit_record.get("target_stock"), "Stage-5 target_stock")
    if target_stock != deficit_target:
        raise ValueError("Stage-4 and Stage-5 target stocks differ")
    lead_time_demand = nonnegative_number(target_record.get("lead_time_demand"),
                                          "lead_time_demand")
    stock = deficit_record.get("current_stock") or {}
    stock_quantity = nonnegative_number(stock.get("quantity"), "current_stock.quantity")
    transit = deficit_record.get("goods_in_transit") or {}
    transit_quantity = nonnegative_number(transit.get("quantity"), "goods_in_transit.quantity")
    if deficit is not None and raw is not None and not math.isclose(deficit, max(0.0, raw), abs_tol=1e-9):
        raise ValueError("Stage-5 deficit does not match raw_deficit")
    if deficit is not None and raw is None:
        raise ValueError("Stage-5 positive/zero deficit lacks raw_deficit")
    if raw is not None and all(value is not None for value in (target_stock, stock_quantity, transit_quantity)):
        if not math.isclose(raw, target_stock - stock_quantity - transit_quantity, abs_tol=1e-9):
            raise ValueError("Stage-5 raw_deficit does not match its inputs")
    if deficit_record.get("status") == "unavailable" and deficit is not None:
        raise ValueError("Unavailable Stage-5 result must not contain a deficit")
    if deficit_record.get("status") not in ("calculated", "provisional", "unavailable"):
        raise ValueError("Unknown Stage-5 status")

    kind = rule_record.get("rule_kind") if rule_record else None
    rule_status = rule_record.get("status") if rule_record else "missing"
    quantity = None
    if deficit is not None and deficit > 0 and deficit_record.get("status") == "calculated" \
            and rule_status == "valid":
        quantity = rule_quantity(rule_record)
        if kind not in ("minimum_dispatch", "multiple"):
            raise ValueError(f"Unknown packing rule kind: {kind}")
        if quantity is None:
            raise ValueError("Valid packing rule lacks quantity")
        if not rule_record.get("source_refs"):
            raise ValueError("Valid packing rule lacks source references")

    reasons: list[str] = []
    urgency_reasons: list[str] = []
    purchase_needed: bool | None = None
    order: int | None = None
    urgency: str | None = None

    if deficit_record.get("status") == "provisional":
        reasons.append("current_inputs_not_confirmed")
        reasons.extend(deficit_record.get("provisional_reasons", []))
        status = "provisional"
    elif deficit is None:
        reasons.extend(deficit_record.get("unavailable_reasons") or ["deficit_unavailable"])
        status = "unavailable"
    elif deficit <= 0:
        purchase_needed = False
        order = 0
        status = "calculated"
    else:
        purchase_needed = True
        if rule_status != "valid" or kind is None or quantity is None:
            reasons.append(f"packing_rule_{rule_status or 'missing'}")
            status = "unavailable"
        else:
            order = rounded_order(deficit, kind, quantity)
            status = "calculated"
            if kind == "minimum_dispatch":
                reasons.append("minimum_dispatch_interpretation_unconfirmed")
                status = "provisional"

    if deficit is not None and deficit_record.get("status") == "calculated":
        if lead_time_demand is None or stock_quantity is None:
            urgency_reasons.append("lead_time_risk_unavailable")
        elif stock_quantity < lead_time_demand:
            urgency = "HIGH"
            urgency_reasons.append("current_stock_below_lead_time_demand")
            if transit_quantity and transit_quantity > 0:
                urgency_reasons.append("incoming_arrival_timing_unverified")
        elif deficit > 0:
            urgency = "MEDIUM"
            urgency_reasons.append("lead_time_covered_but_safety_target_short")
        else:
            urgency = "LOW"
            urgency_reasons.append("target_covered_no_new_order")

    if status not in ("calculated", "provisional", "unavailable"):
        raise ValueError(f"Unknown Stage-5 status: {status}")

    return {
        "source_commit": deficit_record.get("source_commit"),
        "brand": key[0], "sku": key[1], "name": deficit_record.get("name", ""),
        "unit": deficit_record.get("unit"),
        "planning_date": deficit_record.get("planning_date"),
        "target_sha256": deficit_record.get("target_sha256"),
        "balance_sha256": deficit_record.get("balance_sha256"),
        "deficit_sha256": deficit_sha256,
        "rules_sha256": rules_sha256,
        "target_stock": target_stock,
        "lead_time_demand": lead_time_demand,
        "current_stock": stock,
        "goods_in_transit": transit,
        "source_current_stock": deficit_record.get("source_current_stock"),
        "source_goods_in_transit": deficit_record.get("source_goods_in_transit"),
        "input_notes": [note for note in (stock.get("scope_note"), transit.get("scope_note")) if note],
        "raw_deficit": raw,
        "deficit": deficit,
        "packing_rule": rule_record or {"rule_kind": None, "quantity": None,
                                        "status": "missing", "source_refs": [], "notes": []},
        "purchase_needed": purchase_needed,
        "recommended_order": order,
        "urgency": urgency,
        "urgency_reasons": urgency_reasons,
        "status": status,
        "reasons": list(dict.fromkeys(reasons)),
        "deficit_status": deficit_record.get("status"),
        "deficit_unavailable_reasons": deficit_record.get("unavailable_reasons", []),
        "deficit_provisional_reasons": deficit_record.get("provisional_reasons", []),
    }


def load_jsonl(path: Path, label: str) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            key = (row["brand"], row["sku"])
            if key in rows:
                raise ValueError(f"Duplicate {label} SKU at line {line_number}: {key}")
            rows[key] = row
    return rows


def display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}".replace(",", " ") if isinstance(value, float) else str(value)
    return html.escape(str(value))


REASON_LABELS = {
    "current_inputs_not_confirmed": "Текущий остаток или товар в пути не подтверждены: введите актуальные значения.",
    "current_stock:ambiguous_date": "Дата и охват текущего остатка не подтверждены.",
    "goods_in_transit:ambiguous_date": "Дата и охват товара в пути не подтверждены.",
    "minimum_dispatch_interpretation_unconfirmed": "Смысл минимума отгрузки IEK требует подтверждения партнёра.",
    "current_stock_below_lead_time_demand": "Текущий остаток меньше спроса за срок поставки.",
    "incoming_arrival_timing_unverified": "Товар в пути покрывает часть спроса, но срок его прихода для риска не подтверждён.",
    "lead_time_covered_but_safety_target_short": "Спрос за срок поставки покрыт, но до страхового запаса не хватает.",
    "target_covered_no_new_order": "Необходимый запас покрыт; новый заказ по формуле не нужен.",
    "lead_time_risk_unavailable": "Для оценки срочности не хватает прогноза или текущего остатка.",
    "packing_rule_missing": "Правило поставщика отсутствует.",
    "packing_rule_invalid": "Правило поставщика некорректно.",
    "packing_rule_conflict": "В правилах поставщика есть конфликт.",
}


def render_html(result: dict, path: Path) -> None:
    title = html.escape(f"{result['brand']} / {result['sku']}")
    unit = html.escape(result.get("unit") or "ед.")
    rule = result["packing_rule"]
    kind = rule.get("rule_kind")
    kind_label = {"multiple": "Кратность", "minimum_dispatch": "Минимальная отгрузка"}.get(kind, "Правило не найдено")
    urgency_label = {"LOW": "LOW — покрыт необходимый запас",
                     "MEDIUM": "MEDIUM — не хватает страхового запаса",
                     "HIGH": "HIGH — текущего остатка не хватит на срок поставки"}.get(result["urgency"], "Не определена")
    status_label = {"calculated": "Рассчитано по указанным данным", "provisional": "Условный расчёт",
                    "unavailable": "Недоступно"}[result["status"]]
    explanation = ("Положительный дефицит округлён вверх до кратного размера отгрузки."
                   if kind == "multiple" else
                   "Положительный дефицит округлён до целой единицы, затем применён минимум отгрузки."
                   if kind == "minimum_dispatch" else "Правило поставщика не установлено.")
    if result["purchase_needed"] is None:
        explanation = "Исходные данные не подтверждены или недоступны; размер заказа не выдаётся."
    elif result["purchase_needed"] is False:
        explanation = "Необходимый запас покрыт; правило поставщика не требуется для нулевого заказа."
    refs = html.escape(json.dumps({
        "current_stock": result["current_stock"].get("source_refs", []),
        "goods_in_transit": result["goods_in_transit"].get("source_refs", []),
        "replaced_source_current_stock": (result.get("source_current_stock") or {}).get("source_refs", []),
        "replaced_source_goods_in_transit": (result.get("source_goods_in_transit") or {}).get("source_refs", []),
        "packing_rule": rule.get("source_refs", []),
    }, ensure_ascii=False, indent=2))
    note_items = list(dict.fromkeys(result["reasons"] + result["urgency_reasons"]
                                   + rule.get("notes", []) + result["input_notes"]))
    notes = html.escape(" ".join(REASON_LABELS.get(note, note) for note in note_items))
    page = f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Рекомендуемый заказ — {title}</title><style>
body{{font:15px system-ui;margin:32px;max-width:1050px;color:#173329}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}}
.card{{border:1px solid #dce8df;border-radius:9px;padding:16px;min-width:170px}}
.card b{{display:block;font-size:21px;margin-top:8px}}
small{{color:#66786b}}.note{{background:#fff7e6;padding:14px;border-radius:8px}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f5f7f5;padding:14px}}</style>
<h1>Заказ: {title}</h1><p>{html.escape(result.get('name') or '')} · {unit} · {status_label}</p>
<p>Дата планирования: {html.escape(result.get('planning_date') or 'не указана')}. Нужно закупать: <b>{display(result['purchase_needed'])}</b>.</p>
<div class="cards"><div class="card">Необходимый запас<b>{display(result['target_stock'])}</b></div>
<div class="card">Спрос за срок поставки<b>{display(result['lead_time_demand'])}</b></div>
<div class="card">Текущий остаток<b>{display(result['current_stock'].get('quantity'))}</b></div>
<div class="card">В пути<b>{display(result['goods_in_transit'].get('quantity'))}</b></div>
<div class="card">Дефицит<b>{display(result['raw_deficit'])}</b></div></div>
<p>{display(result['target_stock'])} − {display(result['current_stock'].get('quantity'))} −
{display(result['goods_in_transit'].get('quantity'))} = <b>{display(result['raw_deficit'])} {unit}</b>.</p>
<p>{html.escape(kind_label)}: <b>{display(rule.get('quantity'))}</b>. {explanation}</p>
<div class="cards"><div class="card">Рекомендуемый заказ<b>{display(result['recommended_order'])} {unit}</b></div>
<div class="card">Срочность<b>{html.escape(urgency_label)}</b></div></div>
<p class="note">{notes or 'Нет дополнительных замечаний.'} Число — черновая рекомендация; утверждение заказа остаётся за человеком.</p>
<h2>Источники</h2><pre>{refs}</pre>
<small>SHA-256 дефицита: {html.escape(result['deficit_sha256'])}; правил: {html.escape(result['rules_sha256'])}.</small></html>"""
    path.write_text(page, encoding="utf-8")


def write_csv(result: dict, path: Path) -> None:
    fields = ["brand", "sku", "target_stock", "current_stock", "goods_in_transit",
              "raw_deficit", "deficit", "purchase_needed", "rule_kind", "rule_quantity",
              "recommended_order", "urgency", "status", "reasons", "urgency_reasons"]
    row = {field: result.get(field) for field in fields}
    row["current_stock"] = result["current_stock"].get("quantity")
    row["goods_in_transit"] = result["goods_in_transit"].get("quantity")
    row["rule_kind"] = result["packing_rule"].get("rule_kind")
    row["rule_quantity"] = result["packing_rule"].get("quantity")
    row["reasons"] = ";".join(result["reasons"])
    row["urgency_reasons"] = ";".join(result["urgency_reasons"])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET_FILE)
    parser.add_argument("--deficit", type=Path, default=DEFICIT_FILE)
    parser.add_argument("--rules", type=Path, default=RULES_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--sku", action="append", help="focused HTML/CSV/JSON; repeatable")
    parser.add_argument("--brand", choices=("IEK", "Systeme Electric"))
    args = parser.parse_args()
    if args.brand and not args.sku:
        parser.error("--brand requires --sku")
    for path in (args.target, args.deficit, args.rules):
        if not path.is_file():
            parser.error(f"Required input is missing: {path}")
    try:
        targets = load_jsonl(args.target, "Stage-4")
        deficits = load_jsonl(args.deficit, "Stage-5")
        rules = load_jsonl(args.rules, "packing-rule")
        if targets.keys() != deficits.keys():
            raise ValueError("Stage-4 and Stage-5 SKU sets differ")
        extra_rules = len(rules.keys() - deficits.keys())
        target_sha, deficit_sha, rules_sha = (file_hash(path) for path in
                                               (args.target, args.deficit, args.rules))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        selected = []
        counts = {"calculated": 0, "provisional": 0, "unavailable": 0}
        output = args.output_dir / "all-skus.jsonl"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output_dir,
                                             prefix="order-", suffix=".tmp", delete=False) as destination:
                temp_path = Path(destination.name)
                for key, deficit in deficits.items():
                    if deficit.get("source_commit") != SOURCE_COMMIT:
                        raise ValueError(f"Invalid Stage-5 source commit: {key}")
                    if deficit.get("target_sha256") != target_sha:
                        raise ValueError(f"Stale Stage-5 target-file hash: {key}")
                    result = calculate_order(deficit, targets[key], rules.get(key),
                                             deficit_sha256=deficit_sha, rules_sha256=rules_sha)
                    destination.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts[result["status"]] += 1
                    if args.sku and key[1] in args.sku and (not args.brand or key[0] == args.brand):
                        selected.append(result)
            missing = set(args.sku or []) - {item["sku"] for item in selected}
            if missing:
                raise ValueError(f"SKUs not found: {', '.join(sorted(missing))}")
            os.replace(temp_path, output)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))

    for result in selected:
        stem = ("iek-" if result["brand"] == "IEK" else "systeme-") + re.sub(
            r"[^A-Za-z0-9_-]", "-", result["sku"])
        (args.output_dir / f"{stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(result, args.output_dir / f"{stem}.csv")
        render_html(result, args.output_dir / f"{stem}.html")
    print(f"Orders for {sum(counts.values())} SKUs: {output}")
    print("Status:", counts)
    print("Source rules without a Stage-5 SKU:", extra_rules)
    for result in selected:
        print(result["brand"], result["sku"], result["status"],
              "need", result["purchase_needed"], "deficit", result["raw_deficit"],
              "rule", result["packing_rule"].get("rule_kind"),
              result["packing_rule"].get("quantity"), "order", result["recommended_order"],
              "urgency", result["urgency"])


if __name__ == "__main__":
    main()

"""Stage 2: explainable monthly base demand from Stage-1 clean demand JSONL."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from pathlib import Path

from clean_demand import SOURCE_COMMIT

WINDOWS = (("recent_6", 6, 4), ("extended_12", 12, 3), ("historical_32", 32, 1))
OUTPUT_DIR = Path(".analysis/base-demand")
INPUT_FILE = Path(".analysis/clean-demand/all-skus.jsonl")


def usable(period: dict) -> bool:
    value = period.get("clean_demand")
    return not period.get("partial_period", False) and isinstance(value, (int, float)) and value >= 0


def calculate(record: dict, upstream_sha256: str = "") -> dict:
    periods = record["periods"]
    complete = [period for period in periods if not period.get("partial_period", False)]
    if not complete:
        raise ValueError(f"No complete periods for {record['brand']} / {record['sku']}")
    recent = complete[-6:]
    chosen_name, chosen_window = "none", []
    for name, size, minimum in WINDOWS:
        window = complete[-size:]
        if sum(usable(p) for p in window) >= minimum:
            chosen_name, chosen_window = name, window
            break
    if chosen_name == "none":
        chosen_window = complete[-32:]

    current_month = complete[-1]["period"]
    selected = []
    window_periods = []
    for index, period in enumerate(chosen_window):
        age = len(chosen_window) - index
        is_usable = usable(period)
        window_periods.append({
            "period": period["period"], "clean_demand": period.get("clean_demand"),
            "selected": is_usable and chosen_name != "none",
            "reason": "valid" if is_usable else "missing_clean_demand",
        })
        if not is_usable or chosen_name == "none":
            continue
        weight = index + 1
        selected.append({
            "period": period["period"],
            "clean_demand": float(period["clean_demand"]),
            "raw_sales": period.get("raw_sales"),
            "excluded_one_off": period.get("excluded_one_off", 0),
            "estimated_lost_demand": period.get("estimated_lost_demand", 0),
            "stock": period.get("stock"),
            "source_cells": period.get("source_cells"),
            "clean_demand_reasons": period.get("reasons", []),
            "age_months": age, "raw_weight": weight,
        })

    notes = []
    if chosen_name == "extended_12":
        notes.append("fallback_12_months_insufficient_recent_history")
    elif chosen_name == "historical_32":
        notes.append("fallback_32_months_sparse_history")
    elif chosen_name == "none":
        notes.append("no_usable_history")
    if len(recent) - sum(usable(p) for p in recent):
        notes.append("missing_recent_months")

    if selected:
        total_weight = sum(item["raw_weight"] for item in selected)
        for item in selected:
            item["normalized_weight"] = item["raw_weight"] / total_weight
            item["weighted_contribution"] = item["clean_demand"] * item["normalized_weight"]
        base = sum(item["weighted_contribution"] for item in selected)
        newest_age = min(item["age_months"] for item in selected)
        unknown_stock = sum(item["stock"] is None for item in selected)
        adjusted = sum((item["excluded_one_off"] or 0) > 0 for item in selected)
        imputed = sum((item["estimated_lost_demand"] or 0) > 0 for item in selected)
        negative_net = sum("negative_net_sales_return" in item["clean_demand_reasons"] for item in selected)
        quality = max(0.4, 1 - (0.15 * unknown_stock + 0.15 * adjusted
                               + 0.25 * imputed + 0.10 * negative_net) / len(selected))
        history = min(1.0, len(selected) / 6)
        freshness = max(0.25, 1 - 0.1 * (newest_age - 1))
        fallback = {"recent_6": 1.0, "extended_12": 0.75, "historical_32": 0.5}[chosen_name]
        score = round(history * freshness * quality * fallback, 2)
        level = "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"
        if unknown_stock:
            notes.append("unknown_stock_in_selected_months")
        if adjusted:
            notes.append("one_off_adjustment_in_selected_months")
        if imputed:
            notes.append("estimated_stockout_in_selected_months")
        confidence = {
            "level": level, "score": score,
            "factors": {
                "history": round(history, 3), "freshness": round(freshness, 3),
                "quality": round(quality, 3), "fallback": fallback,
                "selected_months": len(selected), "unknown_stock_months": unknown_stock,
                "one_off_adjusted_months": adjusted, "stockout_estimated_months": imputed,
                "negative_net_sales_months": negative_net,
            },
            "reasons": notes,
        }
    else:
        base = None
        confidence = {"level": "unavailable", "score": 0.0, "factors": {
            "history": 0.0, "freshness": 0.0, "quality": 0.0, "fallback": 0.0,
            "selected_months": 0, "unknown_stock_months": 0,
            "one_off_adjusted_months": 0, "stockout_estimated_months": 0,
            "negative_net_sales_months": 0,
        }, "reasons": notes}
    return {
        "source_commit": record["source_commit"], "upstream_sha256": upstream_sha256,
        "brand": record["brand"], "sku": record["sku"], "name": record.get("name", ""),
        "unit": record.get("unit"), "as_of_complete_month": current_month,
        "method": chosen_name, "base_demand_monthly": base, "confidence": confidence,
        "window_periods": window_periods, "selected_periods": selected,
    }


def render_html(result: dict, path: Path) -> None:
    def show(value: object) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return html.escape(str(value))
    rows = []
    for item in result["selected_periods"]:
        rows.append("<tr>" + "".join(f"<td>{show(item[key])}</td>" for key in
                    ("period", "clean_demand", "age_months", "raw_weight",
                     "normalized_weight", "weighted_contribution")) + "</tr>")
    omitted = ", ".join(item["period"] for item in result["window_periods"] if not item["selected"])
    title = html.escape(f"{result['brand']} / {result['sku']}")
    markup = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Базовый спрос — {title}</title>
<style>body{{font:15px system-ui;margin:32px;max-width:1100px}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#f3f5f7}}
.metric{{font-size:2rem;font-weight:700}}code{{background:#f3f5f7;padding:2px 5px}}</style>
<h1>Базовый спрос: {title}</h1>
<p>Последний полный месяц: <b>{result['as_of_complete_month']}</b>. Метод: <code>{result['method']}</code>.</p>
<p class="metric">{show(result['base_demand_monthly'])} {html.escape(result.get('unit') or '')} / месяц</p>
<p>Уверенность: <b>{result['confidence']['level']}</b> ({show(result['confidence']['score'])}).
Причины: {html.escape(', '.join(result['confidence']['reasons'])) or '—'}.</p>
<p>Формула: сумма <code>clean demand × нормализованный вес</code>. Более свежим месяцам дан больший вес.</p>
<table><thead><tr><th>Период</th><th>Clean demand</th><th>Возраст, мес.</th>
<th>Исходный вес</th><th>Нормализованный вес</th><th>Вклад</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p>Пропущенные периоды выбранного окна: {html.escape(omitted) or 'нет'}.</p>
<p>Исходная трассировка продаж и корректировок: <code>.analysis/clean-demand/all-skus.jsonl</code>.
SHA-256 входа: <code>{result['upstream_sha256']}</code>.</p></html>"""
    path.write_text(markup, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--sku", action="append", help="write focused HTML/CSV/JSON; repeatable")
    parser.add_argument("--brand", choices=("IEK", "Systeme Electric"))
    args = parser.parse_args()
    if args.brand and not args.sku:
        parser.error("--brand requires --sku")
    if not args.input.is_file():
        parser.error(f"{args.input} is missing; run python backend/clean_demand.py first")
    checksum = hashlib.sha256()
    with args.input.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    digest = checksum.hexdigest()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = []
    count = 0
    output = args.output_dir / "all-skus.jsonl"
    with args.input.open(encoding="utf-8") as source, output.open("w", encoding="utf-8") as target:
        for line in source:
            upstream = json.loads(line)
            if upstream.get("source_commit") != SOURCE_COMMIT:
                raise SystemExit("Stage-1 output has a different source commit; regenerate it")
            result = calculate(upstream, digest)
            target.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
            if args.sku and result["sku"] in args.sku and (not args.brand or result["brand"] == args.brand):
                selected.append(result)
    missing = set(args.sku or []) - {item["sku"] for item in selected}
    if missing:
        raise SystemExit(f"SKUs not found: {', '.join(sorted(missing))}")
    for result in selected:
        stem = ("iek-" if result["brand"] == "IEK" else "systeme-") + re.sub(
            r"[^A-Za-z0-9_-]", "-", result["sku"])
        (args.output_dir / f"{stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with (args.output_dir / f"{stem}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "period", "clean_demand", "age_months", "raw_weight",
                "normalized_weight", "weighted_contribution"])
            writer.writeheader()
            writer.writerows({key: item[key] for key in writer.fieldnames}
                             for item in result["selected_periods"])
        render_html(result, args.output_dir / f"{stem}.html")
    print(f"Base demand for {count} SKUs: {output}")
    for result in selected:
        print(result["brand"], result["sku"], result["method"],
              result["base_demand_monthly"], result["confidence"]["level"])


if __name__ == "__main__":
    main()

"""Stage 3: monthly forecast with separate robust trend and SKU seasonality."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

from clean_demand import SOURCE_COMMIT

STAGE1_FILE = Path(".analysis/clean-demand/all-skus.jsonl")
STAGE2_FILE = Path(".analysis/base-demand/all-skus.jsonl")
OUTPUT_DIR = Path(".analysis/forecast")


def month_number(month: str) -> int:
    year, number = map(int, month.split("-"))
    if not 1 <= number <= 12:
        raise ValueError(f"Invalid month: {month}")
    return year * 12 + number - 1


def add_month(month: str, offset: int) -> str:
    index = month_number(month) + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def valid_history(clean: dict) -> list[dict]:
    return [p for p in clean["periods"]
            if not p.get("partial_period", False)
            and isinstance(p.get("clean_demand"), (int, float))
            and math.isfinite(p["clean_demand"]) and p["clean_demand"] >= 0]


def seasonality_profile(clean: dict) -> dict:
    history = valid_history(clean)
    by_year: dict[str, list[dict]] = defaultdict(list)
    for period in history:
        by_year[period["period"][:4]].append(period)
    year_medians = {}
    for year, periods in by_year.items():
        if len(periods) >= 10:
            median = statistics.median(p["clean_demand"] for p in periods)
            if median > 0:
                year_medians[year] = median
    if len(history) < 24 or len(year_medians) < 2:
        return {"status": "neutral_insufficient_history", "year_medians": year_medians,
                "indices": {}, "evidence": {}}
    evidence: dict[str, list[dict]] = defaultdict(list)
    for period in history:
        year = period["period"][:4]
        if year not in year_medians:
            continue
        calendar_month = period["period"][-2:]
        evidence[calendar_month].append({
            "period": period["period"], "clean_demand": period["clean_demand"],
            "year_median": year_medians[year],
            "ratio": period["clean_demand"] / year_medians[year],
            "source_cells": period.get("source_cells"),
        })
    indices = {}
    for month, observations in evidence.items():
        if len({item["period"][:4] for item in observations}) >= 2:
            raw = statistics.median(item["ratio"] for item in observations)
            indices[month] = {"raw_index": raw, "index": min(1.5, max(0.5, raw)),
                              "observation_count": len(observations)}
    return {"status": "sku_history" if indices else "neutral_insufficient_month_repeats",
            "year_medians": year_medians, "indices": indices, "evidence": dict(evidence)}


def trend_evidence(clean: dict, base: dict, seasonality: dict) -> dict:
    complete = [p for p in clean["periods"] if not p.get("partial_period", False)]
    window = complete[-12:]
    usable = [p for p in window if isinstance(p.get("clean_demand"), (int, float))
              and math.isfinite(p["clean_demand"]) and p["clean_demand"] >= 0]
    base_value = base["base_demand_monthly"]
    evidence = []
    for period in usable:
        index = seasonality["indices"].get(period["period"][-2:], {}).get("index", 1.0)
        evidence.append({
            "period": period["period"], "clean_demand": period["clean_demand"],
            "seasonality_index": index, "deseasonalized_demand": period["clean_demand"] / index,
            "source_cells": period.get("source_cells"),
        })
    result = {
        "status": "neutral", "reason": "insufficient_history", "slope_per_month": 0.0,
        "raw_theil_sen_slope": None, "early_median": None, "late_median": None,
        "history_deseasonalization": "sku_month_index" if seasonality["indices"]
        else "neutral_no_sku_profile",
        "evidence": evidence,
    }
    if base_value is None or base_value <= 0:
        result["reason"] = "base_demand_unavailable_or_zero"
        return result
    first_half = [item["deseasonalized_demand"] for item in evidence
                  if item["period"] in {p["period"] for p in window[:6]}]
    second_half = [item["deseasonalized_demand"] for item in evidence
                   if item["period"] in {p["period"] for p in window[6:]}]
    if len(usable) < 8 or len(first_half) < 3 or len(second_half) < 3:
        return result
    slopes = [
        (right["deseasonalized_demand"] - left["deseasonalized_demand"]) /
        (month_number(right["period"]) - month_number(left["period"]))
        for i, left in enumerate(evidence) for right in evidence[i + 1:]
    ]
    raw_slope = statistics.median(slopes)
    early, late = statistics.median(first_half), statistics.median(second_half)
    result.update({"raw_theil_sen_slope": raw_slope, "early_median": early,
                   "late_median": late, "reason": "no_sustained_shift"})
    minimum_shift = max(0.15 * max(base_value, 1), 1)
    minimum_slope = max(0.01 * max(base_value, 1), 0.1)
    if abs(late - early) < minimum_shift or abs(raw_slope) < minimum_slope:
        return result
    if (late - early) * raw_slope <= 0:
        result["reason"] = "median_shift_disagrees_with_robust_slope"
        return result
    limited = min(0.05 * base_value, max(-0.05 * base_value, raw_slope))
    result.update({"status": "applied", "reason": "sustained_rise" if limited > 0
                   else "sustained_decline", "slope_per_month": limited})
    return result


def forecast(clean: dict, base: dict, months: int = 6, start_month: str | None = None,
             stage1_sha256: str = "", stage2_sha256: str = "") -> dict:
    if (clean["brand"], clean["sku"]) != (base["brand"], base["sku"]):
        raise ValueError("Stage 1 and 2 SKU keys differ")
    if clean["source_commit"] != base["source_commit"] or clean["source_commit"] != SOURCE_COMMIT:
        raise ValueError("Stage 1 and 2 source commits differ")
    as_of = base["as_of_complete_month"]
    first = start_month or add_month(as_of, 1)
    if month_number(first) <= month_number(as_of):
        raise ValueError("Forecast must start after the last complete month")
    if not 1 <= months <= 24:
        raise ValueError("Forecast horizon must be 1–24 months")
    seasonal = seasonality_profile(clean)
    trend = trend_evidence(clean, base, seasonal)
    base_value = base["base_demand_monthly"]
    selected = base["selected_periods"]
    if selected:
        base_window_index = sum(
            item["normalized_weight"] *
            seasonal["indices"].get(item["period"][-2:], {}).get("index", 1.0)
            for item in selected
        )
    else:
        base_window_index = 1.0
    predictions = []
    for offset in range(months):
        target = add_month(first, offset)
        steps = month_number(target) - month_number(as_of)
        target_profile = seasonal["indices"].get(target[-2:])
        if base_value is None:
            trend_adjustment = seasonality_adjustment = final = None
            multiplier = 1.0
            reason = "base_demand_unavailable"
        else:
            trend_adjustment = max(-0.3 * base_value, min(0.3 * base_value,
                               trend["slope_per_month"] * steps))
            after_trend = max(0.0, base_value + trend_adjustment)
            if target_profile:
                multiplier = max(0.5, min(1.5, target_profile["index"] / base_window_index))
                reason = "sku_seasonality"
            else:
                multiplier = 1.0
                reason = "neutral_seasonality_insufficient_history"
            seasonality_adjustment = after_trend * (multiplier - 1)
            final = max(0.0, after_trend + seasonality_adjustment)
        predictions.append({
            "month": target, "month_kind": "current_partial_month" if target == add_month(as_of, 1)
            and any(p["period"] == target and p.get("partial_period") for p in clean["periods"])
            else "future_full_month",
            "base_demand": base_value, "steps_from_base_month": steps,
            "trend_adjustment": trend_adjustment,
            "target_seasonality_index": target_profile["index"] if target_profile else None,
            "base_window_seasonality_index": base_window_index,
            "seasonality_multiplier": multiplier,
            "seasonality_adjustment": seasonality_adjustment,
            "final_forecast": final, "reason": reason,
        })
    return {
        "source_commit": SOURCE_COMMIT, "stage1_sha256": stage1_sha256,
        "stage2_sha256": stage2_sha256, "brand": clean["brand"], "sku": clean["sku"],
        "name": clean.get("name", ""), "unit": clean.get("unit"),
        "as_of_complete_month": as_of, "base_demand_monthly": base_value,
        "base_confidence": base["confidence"], "trend": trend, "seasonality": seasonal,
        "history": [{"period": p["period"], "clean_demand": p.get("clean_demand"),
                     "partial_period": p.get("partial_period", False),
                     "source_cells": p.get("source_cells")} for p in clean["periods"]],
        "forecast_months": predictions,
    }


def render_html(result: dict, path: Path) -> None:
    def show(value: object) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.2f}"
        return html.escape(str(value))
    rows = []
    for item in result["forecast_months"]:
        rows.append("<tr>" + "".join(f"<td>{show(item[key])}</td>" for key in
                    ("month", "base_demand", "trend_adjustment",
                     "seasonality_adjustment", "final_forecast"))
                    + f"<td>{html.escape(item['reason'])}</td></tr>")
    history = [p for p in result["history"] if not p["partial_period"]]
    future = result["forecast_months"]
    width, height = 1160, 350
    max_value = max([p["clean_demand"] for p in history if p["clean_demand"] is not None]
                    + [p["final_forecast"] for p in future if p["final_forecast"] is not None]
                    + [1])
    def xy(index: int, value: float) -> tuple[float, float]:
        return 40 + index * 28, height - 30 - max(0, value) / max_value * (height - 65)
    points = [xy(i, p["clean_demand"]) if p["clean_demand"] is not None else None
              for i, p in enumerate(history)]
    future_points = [xy(len(history) + i, p["final_forecast"])
                     if p["final_forecast"] is not None else None for i, p in enumerate(future)]
    def draw_line(series: list[tuple[float, float] | None], color: str) -> str:
        lines = [f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                 f'stroke="{color}" stroke-width="2"/>' for a, b in zip(series, series[1:])
                 if a is not None and b is not None]
        dots = [f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="2.6" fill="{color}"/>'
                for p in series if p is not None]
        return "".join(lines + dots)
    labels = "".join(f'<text x="{40+i*28}" y="{height-10}" font-size="9" '
                     f'text-anchor="middle">{p["period"][2:]}</text>'
                     for i, p in enumerate(history) if i % 4 == 0)
    labels += "".join(f'<text x="{40+(len(history)+i)*28}" y="{height-10}" font-size="9" '
                      f'text-anchor="middle">{p["month"][2:]}</text>'
                      for i, p in enumerate(future))
    title = html.escape(f"{result['brand']} / {result['sku']}")
    markup = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Прогноз — {title}</title>
<style>body{{font:15px system-ui;margin:32px;max-width:1200px}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#f3f5f7}}
svg{{width:100%;height:auto}}.legend span{{margin-right:24px}}</style>
<h1>Прогноз спроса: {title}</h1>
<p>База: {show(result['base_demand_monthly'])} {html.escape(result.get('unit') or '')} / месяц;
уверенность базы: {result['base_confidence']['level']}. Тренд: {result['trend']['reason']},
наклон {show(result['trend']['slope_per_month'])} в месяц.
Сезонность: {result['seasonality']['status']}.</p>
<div class="legend"><span style="color:#2563eb">● clean demand</span>
<span style="color:#e86d24">● forecast</span></div>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="История очищенного спроса и прогноз">
<line x1="40" y1="{height-30}" x2="{width-20}" y2="{height-30}" stroke="#999"/>
{draw_line(points, '#2563eb')}{draw_line(future_points, '#e86d24')}{labels}</svg>
<p>Первый месяц может быть текущим неполным месяцем; значения в таблице относятся к полному календарному месяцу.</p>
<table><thead><tr><th>Месяц</th><th>Base demand</th><th>Trend adjustment</th>
<th>Seasonality adjustment</th><th>Final forecast</th><th>Основание сезонности</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p>Точные значения, месяцы истории, медианы, индексы, ограничения и ссылки на исходные ячейки — в JSON рядом.</p></html>"""
    path.write_text(markup, encoding="utf-8")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1", type=Path, default=STAGE1_FILE)
    parser.add_argument("--stage2", type=Path, default=STAGE2_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--sku", action="append", help="write focused HTML/CSV/JSON; repeatable")
    parser.add_argument("--brand", choices=("IEK", "Systeme Electric"))
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--start-month", help="YYYY-MM; default first month after last complete month")
    args = parser.parse_args()
    if args.brand and not args.sku:
        parser.error("--brand requires --sku")
    if not args.stage1.is_file() or not args.stage2.is_file():
        parser.error("Stage-1 and Stage-2 JSONL are required; run the earlier stages first")
    if args.start_month:
        month_number(args.start_month)
    stage1_hash, stage2_hash = file_hash(args.stage1), file_hash(args.stage2)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = []
    count = 0
    output = args.output_dir / "all-skus.jsonl"
    with args.stage1.open(encoding="utf-8") as first, args.stage2.open(encoding="utf-8") as second, \
            output.open("w", encoding="utf-8") as target:
        for first_line, second_line in zip(first, second, strict=True):
            clean, base = json.loads(first_line), json.loads(second_line)
            if base.get("upstream_sha256") != stage1_hash:
                raise SystemExit("Stage-2 output is stale relative to Stage-1; rerun base_demand.py")
            result = forecast(clean, base, args.months, args.start_month,
                              stage1_hash, stage2_hash)
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
                "month", "base_demand", "trend_adjustment",
                "seasonality_adjustment", "final_forecast"])
            writer.writeheader()
            writer.writerows({key: item[key] for key in writer.fieldnames}
                             for item in result["forecast_months"])
        render_html(result, args.output_dir / f"{stem}.html")
    print(f"Forecast for {count} SKUs: {output}")
    for result in selected:
        print(result["brand"], result["sku"], result["trend"]["reason"],
              result["seasonality"]["status"],
              [(p["month"], round(p["final_forecast"], 2) if p["final_forecast"] is not None else None)
               for p in result["forecast_months"]])


if __name__ == "__main__":
    main()

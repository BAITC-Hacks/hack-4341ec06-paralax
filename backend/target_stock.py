"""Stage 4: traceable target stock from monthly forecast and explicit parameters."""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import html
import json
import math
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

from clean_demand import SOURCE_COMMIT
from forecast_demand import file_hash

INPUT_FILE = Path(".analysis/forecast/all-skus.jsonl")
OUTPUT_DIR = Path(".analysis/target-stock")


def parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid planning date {value!r}; use YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError(f"Invalid planning date {value!r}; use YYYY-MM-DD")
    return parsed


def calculate_target_stock(
    forecast_record: dict,
    planning_date: str,
    lead_time_days: int,
    safety_stock_days: float,
    upstream_sha256: str = "",
) -> dict:
    """Cover [planning_date, planning_date + lead_time_days) with prorated months.

    A missing calendar month is an input error. A present month with an unknown
    forecast yields an unavailable target, never an invented zero.
    """
    start = parse_date(planning_date)
    if isinstance(lead_time_days, bool) or not isinstance(lead_time_days, int) or lead_time_days < 1:
        raise ValueError("lead_time_days must be a positive integer")
    if (isinstance(safety_stock_days, bool)
            or not isinstance(safety_stock_days, (int, float))
            or not math.isfinite(safety_stock_days) or safety_stock_days < 0):
        raise ValueError("safety_stock_days must be a finite nonnegative number")
    try:
        end = start + timedelta(days=lead_time_days)
    except OverflowError as error:
        raise ValueError("lead_time_days extends beyond supported dates") from error
    last_complete = forecast_record.get("as_of_complete_month")
    if last_complete and planning_date[:7] <= last_complete:
        raise ValueError("planning_date must follow the last complete forecast-history month")

    forecasts = {}
    for item in forecast_record["forecast_months"]:
        month = item["month"]
        if month in forecasts:
            raise ValueError(f"Duplicate forecast month: {month}")
        forecasts[month] = item

    months = []
    unavailable_reasons = []
    cursor = start
    while cursor < end:
        month = cursor.strftime("%Y-%m")
        if month not in forecasts:
            raise ValueError(f"Forecast month {month} is missing; extend Stage 3 --months")
        year, number = cursor.year, cursor.month
        days_in_month = calendar.monthrange(year, number)[1]
        month_end = date(year + (number == 12), number % 12 + 1, 1)
        covered_end = min(month_end, end)
        covered_days = (covered_end - cursor).days
        source = forecasts[month]
        monthly = source.get("final_forecast")
        if monthly is not None and (isinstance(monthly, bool)
                                    or not isinstance(monthly, (int, float))
                                    or not math.isfinite(monthly) or monthly < 0):
            raise ValueError(f"Invalid monthly forecast for {month}: {monthly!r}")
        if monthly is None:
            unavailable_reasons.append(f"forecast_unavailable:{month}")
        daily = monthly / days_in_month if monthly is not None else None
        months.append({
            "month": month,
            "covered_start": cursor.isoformat(),
            "covered_end_exclusive": covered_end.isoformat(),
            "covered_days": covered_days,
            "days_in_month": days_in_month,
            "monthly_forecast": monthly,
            "daily_forecast": daily,
            "demand_contribution": daily * covered_days if daily is not None else None,
            "base_demand": source.get("base_demand"),
            "trend_adjustment": source.get("trend_adjustment"),
            "seasonality_adjustment": source.get("seasonality_adjustment"),
            "forecast_reason": source.get("reason"),
        })
        cursor = covered_end

    lead_demand = (math.fsum(item["demand_contribution"] for item in months)
                   if not unavailable_reasons else None)
    average_daily = lead_demand / lead_time_days if lead_demand is not None else None
    safety = average_daily * safety_stock_days if average_daily is not None else None
    target = lead_demand + safety if lead_demand is not None else None
    return {
        "source_commit": forecast_record.get("source_commit"),
        "stage1_sha256": forecast_record.get("stage1_sha256"),
        "stage2_sha256": forecast_record.get("stage2_sha256"),
        "upstream_sha256": upstream_sha256,
        "brand": forecast_record["brand"],
        "sku": forecast_record["sku"],
        "name": forecast_record.get("name", ""),
        "unit": forecast_record.get("unit"),
        "as_of_complete_month": last_complete,
        "planning_date": start.isoformat(),
        "horizon_end_exclusive": end.isoformat(),
        "lead_time_days": lead_time_days,
        "lead_time_source": "explicit_planning_parameter_not_in_workbooks",
        "safety_stock_days": safety_stock_days,
        "safety_stock_method": "average_daily_forecast_over_lead_time_times_safety_stock_days",
        "forecast_months_in_lead_time": months,
        "lead_time_demand": lead_demand,
        "average_daily_forecast": average_daily,
        "safety_stock": safety,
        "target_stock": target,
        "status": "unavailable" if unavailable_reasons else "calculated",
        "unavailable_reasons": unavailable_reasons,
    }


def display_number(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ")
    return html.escape(str(value))


def render_html(result: dict, path: Path) -> None:
    title = html.escape(f"{result['brand']} / {result['sku']}")
    unit = html.escape(result.get("unit") or "ед.")
    rows = "".join(
        f"<tr><td>{html.escape(item['month'])}</td>"
        f"<td>{item['covered_start']} — {item['covered_end_exclusive']} (не включая)</td>"
        f"<td>{item['covered_days']} / {item['days_in_month']}</td>"
        f"<td>{display_number(item['monthly_forecast'])}</td>"
        f"<td>{display_number(item['demand_contribution'])}</td></tr>"
        for item in result["forecast_months_in_lead_time"]
    )
    status = ("Рассчитано" if result["status"] == "calculated"
              else "Недоступно: " + ", ".join(result["unavailable_reasons"]))
    markup = f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Необходимый запас — {title}</title>
<style>body{{font:15px system-ui;margin:32px;max-width:1150px;color:#173329}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}
th{{background:#f3f7f4}}.cards{{display:flex;gap:14px;flex-wrap:wrap;margin:24px 0}}
.card{{border:1px solid #dce8df;border-radius:9px;padding:16px;min-width:180px}}
.card b{{display:block;font-size:21px;margin-top:8px}}small{{color:#66786b}}</style>
<h1>Необходимый запас: {title}</h1>
<p>{html.escape(result.get('name') or '')} · единица: {unit} · статус: {html.escape(status)}</p>
<p>Дата начала: <b>{result['planning_date']}</b>; срок поставки: <b>{result['lead_time_days']} дней</b>
(явно заданный параметр, не извлечён из Excel). Горизонт до {result['horizon_end_exclusive']} исключительно.
Месячный прогноз распределён равномерно по календарным дням.</p>
<table><thead><tr><th>Месяц</th><th>Период в сроке поставки</th><th>Дней / в месяце</th>
<th>Прогноз за месяц</th><th>Вклад в спрос</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="cards"><div class="card">Спрос за срок поставки<b>{display_number(result['lead_time_demand'])} {unit}</b></div>
<div class="card">Страховой запас<b>{display_number(result['safety_stock'])} {unit}</b>
<small>{result['safety_stock_days']:g} дней × средний прогноз {display_number(result['average_daily_forecast'])} {unit}/день</small></div>
<div class="card">Необходимый запас<b>{display_number(result['target_stock'])} {unit}</b></div></div>
<p>Формула: необходимый запас = спрос за срок поставки + страховой запас.
Здесь ещё не учитываются остаток, товар в пути, дефицит и кратность заказа.</p>
<small>Этап 3: SHA-256 <code>{html.escape(result['upstream_sha256'])}</code>;
исходные книги: Git <code>{html.escape(result.get('source_commit') or '')}</code>.
Полная помесячная трассировка этапа 3 и ссылки на исходные ячейки находятся в его JSON.</small></html>"""
    path.write_text(markup, encoding="utf-8")


def write_csv(result: dict, path: Path) -> None:
    fields = [
        "row_kind", "month", "covered_start", "covered_end_exclusive", "covered_days",
        "days_in_month", "monthly_forecast", "daily_forecast", "demand_contribution",
        "lead_time_demand", "safety_stock_days", "average_daily_forecast",
        "safety_stock", "target_stock", "status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in result["forecast_months_in_lead_time"]:
            writer.writerow({key: ("month" if key == "row_kind" else item.get(key))
                             for key in fields})
        writer.writerow({key: ("total" if key == "row_kind" else result.get(key))
                         for key in fields})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--planning-date", required=True, help="first covered day, YYYY-MM-DD")
    parser.add_argument("--lead-time-days", required=True, type=int,
                        help="explicit delivery lead time; unavailable in workbooks")
    parser.add_argument("--safety-stock-days", required=True, type=float,
                        help="explicit days of average forecast used as safety stock")
    parser.add_argument("--sku", action="append", help="write focused HTML/CSV/JSON; repeatable")
    parser.add_argument("--brand", choices=("IEK", "Systeme Electric"))
    args = parser.parse_args()
    if args.brand and not args.sku:
        parser.error("--brand requires --sku")
    if not args.input.is_file():
        parser.error(f"{args.input} is missing; run the previous stages first")
    try:
        parse_date(args.planning_date)
        if args.lead_time_days < 1:
            raise ValueError("lead_time_days must be a positive integer")
        if not math.isfinite(args.safety_stock_days) or args.safety_stock_days < 0:
            raise ValueError("safety_stock_days must be a finite nonnegative number")
    except ValueError as error:
        parser.error(str(error))

    upstream_sha256 = file_hash(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = []
    count = unavailable = 0
    seen_keys = set()
    source_lineage = None
    output = args.output_dir / "all-skus.jsonl"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output_dir,
                                         prefix="target-stock-", suffix=".tmp", delete=False) as target:
            temp_path = Path(target.name)
            with args.input.open(encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    forecast_record = json.loads(line)
                    key = (forecast_record["brand"], forecast_record["sku"])
                    if key in seen_keys:
                        raise ValueError(f"Duplicate SKU in Stage 3 at line {line_number}: {key}")
                    seen_keys.add(key)
                    lineage = (forecast_record.get("source_commit"),
                               forecast_record.get("stage1_sha256"),
                               forecast_record.get("stage2_sha256"))
                    if lineage[0] != SOURCE_COMMIT or not lineage[1] or not lineage[2]:
                        raise ValueError(f"Invalid Stage-3 lineage at line {line_number}")
                    if source_lineage is None:
                        source_lineage = lineage
                    elif lineage != source_lineage:
                        raise ValueError(f"Mixed Stage-3 lineage at line {line_number}")
                    try:
                        result = calculate_target_stock(
                            forecast_record, args.planning_date, args.lead_time_days,
                            args.safety_stock_days, upstream_sha256)
                    except ValueError as error:
                        raise ValueError(f"{key[0]} / {key[1]}: {error}") from error
                    target.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                    count += 1
                    unavailable += result["status"] == "unavailable"
                    if (args.sku and key[1] in args.sku
                            and (not args.brand or key[0] == args.brand)):
                        selected.append(result)
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
    print(f"Target stock for {count} SKUs ({unavailable} unavailable): {output}")
    print(f"Stage-3 SHA-256: {upstream_sha256}")
    for result in selected:
        print(result["brand"], result["sku"], result["status"],
              "lead-time demand", display_number(result["lead_time_demand"]),
              "safety", display_number(result["safety_stock"]),
              "target", display_number(result["target_stock"]))


if __name__ == "__main__":
    main()

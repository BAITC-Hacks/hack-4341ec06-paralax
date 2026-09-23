"""Readable, self-contained Stage-7 trace for one SKU.

The caller supplies the six already-calculated per-SKU records. This renderer
does not recalculate demand or write partner-derived data into the repository.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def shown(value: Any) -> str:
    """Plain-text representation; retain full numeric precision for auditing."""
    if value is None:
        return "—"
    if value is True:
        return "Да"
    if value is False:
        return "Нет"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return str(value)


def escaped(value: Any) -> str:
    return html.escape(shown(value), quote=True)


def json_block(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2), quote=True)


def table(headings: list[str], rows: list[list[Any]], empty: str = "Нет записей") -> str:
    header = "".join(f"<th scope=\"col\">{escaped(title)}</th>" for title in headings)
    body = "".join("<tr>" + "".join(f"<td>{escaped(cell)}</td>" for cell in row) + "</tr>"
                   for row in rows)
    if not body:
        body = f'<tr><td colspan="{len(headings)}">{escaped(empty)}</td></tr>'
    return f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def details(title: str, content: str, *, open_by_default: bool = False) -> str:
    opened = " open" if open_by_default else ""
    return f'<details{opened}><summary>{escaped(title)}</summary>{content}</details>'


def source_cell(source: dict, cell: dict | None) -> str:
    if not cell:
        return "—"
    column = cell.get("column")
    letters = ""
    if isinstance(column, int) and column > 0:
        while column:
            column, remainder = divmod(column - 1, 26)
            letters = chr(65 + remainder) + letters
    row = cell.get("row")
    address = f"{letters}{row}" if letters and row else shown(cell)
    return f"{source.get('file', 'источник не указан')} · {source.get('sheet', 'лист не указан')} · {address}"


def source_refs(refs: Any) -> str:
    if not refs:
        return "—"
    parts = []
    for ref in refs:
        if not isinstance(ref, dict):
            parts.append(shown(ref))
            continue
        head = [shown(ref.get(key)) for key in ("file", "sheet", "cell") if ref.get(key)]
        if not head:
            head = [shown(ref.get("source") or ref.get("kind") or "Запись пользователя")]
        extra = [f"{key}={shown(value)}" for key, value in ref.items()
                 if key not in ("file", "sheet", "cell") and value is not None]
        parts.append(" · ".join(head + extra))
    return "\n".join(parts)


def source_evidence(label: str, evidence: dict | None) -> str:
    if not evidence:
        return f"<h3>{escaped(label)}</h3><p>Источник отсутствует.</p>"
    basis = evidence.get("basis") or ""
    origin = ("Введено и подтверждено пользователем; автоматической сверки со складом нет"
              if basis == "user_entered_attested" else
              "Из файла Excel" if any(isinstance(ref, dict) and ref.get("file")
                                   for ref in evidence.get("source_refs") or []) else
              "Источник не установлен")
    rows = [["Происхождение", origin],
            ["Количество", evidence.get("quantity")], ["Качество", evidence.get("quality")],
            ["Дата", evidence.get("as_of_date")], ["Основание", evidence.get("basis")],
            ["Проверка", evidence.get("verification")],
            ["Охват и замечание", evidence.get("scope_note")],
            ["Файл / лист / ячейка / ввод", source_refs(evidence.get("source_refs"))]]
    return f"<h3>{escaped(label)}</h3>{table(['Поле', 'Значение'], rows)}"


def render_trace_html(trace: dict, path: Path) -> None:
    """Write an auditable Russian trace from Stage 1 through Stage 6.

    Strings and source paths in every table and raw JSON block are HTML-escaped.
    All six records remain available verbatim in the expandable appendix.
    """
    stages = {number: trace.get(f"stage{number}") or {} for number in range(1, 7)}
    s1, s2, s3, s4, s5, s6 = (stages[number] for number in range(1, 7))
    source_files = s1.get("source_files") or {}
    name = trace.get("name") or s6.get("name") or s1.get("name") or ""
    unit = trace.get("unit") or s6.get("unit") or s1.get("unit") or "ед."
    brand = trace.get("brand") or s6.get("brand") or s1.get("brand") or ""
    sku = trace.get("sku") or s6.get("sku") or s1.get("sku") or ""

    stage1_rows = []
    for period in s1.get("periods") or []:
        cells = period.get("source_cells") or {}
        stage1_rows.append([
            period.get("period"), period.get("raw_sales"), period.get("observed_demand"),
            period.get("document_month_total"),
            period.get("document_reconciled"),
            period.get("excluded_one_off"), period.get("adjusted_sales"),
            period.get("stock"), period.get("estimated_lost_demand"),
            period.get("seasonality_multiplier"),
            ", ".join(period.get("reference_periods") or []) or "—",
            period.get("clean_demand"), ", ".join(period.get("reasons") or []) or "—",
            source_cell(source_files.get("sales") or {}, cells.get("sales")),
            source_cell(source_files.get("stock") or {}, cells.get("stock")),
        ])
    document_rows = [[item.get("month"), item.get("document"), item.get("quantity"),
                      item.get("unit"), source_cell(source_files.get("documents") or {},
                                                    {"row": item.get("row"), "column": 8})]
                     for item in s1.get("document_movements") or []]
    outlier_rows = [[period.get("period"), item.get("document"), item.get("quantity"),
                     item.get("excluded_excess"),
                     source_cell(source_files.get("documents") or {},
                                 {"row": item.get("row"), "column": 8})]
                    for period in s1.get("periods") or []
                    for item in period.get("outlier_documents") or []]
    stage1 = f"""<section id="stage1"><h2>1. Продажи → очищенный спрос</h2>
    <p>Исходная продажа сохраняется. Корректировки крупных документов и оценка упущенного спроса
    показаны отдельно; отсутствие данных не заменяется нулём.</p>
    {table(['Месяц', 'Продажи', 'Наблюдаемый спрос', 'Сумма документов', 'Сверка документов',
            'Разовая продажа исключена', 'После исключения', 'Месячный остаток', 'Оценка упущенного спроса',
            'Множитель для восстановления', 'Опорные месяцы',
            'Очищенный спрос', 'Причины', 'Источник продажи', 'Источник остатка'], stage1_rows)}
    {details('Отмеченные крупные документы и исключённая часть',
             table(['Месяц', 'Документ', 'Количество', 'Исключено из регулярного спроса',
                    'Источник'], outlier_rows))}
    {details('Документы продажи: исходные строки и номера',
             table(['Месяц', 'Документ', 'Количество', 'Единица', 'Источник'], document_rows))}
    {details('Порог разовой продажи и дополнительные поля этапа 1',
             f'<pre>{json_block({"outlier_rule": s1.get("outlier_rule"), "source_files": source_files})}</pre>')}
    </section>"""

    selected_rows = [[item.get("period"), item.get("clean_demand"), item.get("raw_sales"),
                      item.get("excluded_one_off"), item.get("estimated_lost_demand"),
                      item.get("raw_weight"), item.get("normalized_weight"),
                      item.get("weighted_contribution"),
                      source_cell(source_files.get("sales") or {}, (item.get("source_cells") or {}).get("sales"))]
                     for item in s2.get("selected_periods") or []]
    confidence = s2.get("confidence") or {}
    window_rows = [[item.get("period"), item.get("clean_demand"), item.get("selected"),
                    item.get("reason")]
                   for item in s2.get("window_periods") or []]
    stage2 = f"""<section id="stage2"><h2>2. Базовый спрос</h2>
    <p>Окно: <strong>{escaped(s2.get('method'))}</strong>. База = сумма «очищенный спрос ×
    нормализованный вес» = <strong>{escaped(s2.get('base_demand_monthly'))} {escaped(unit)} / месяц</strong>.
    Уверенность: {escaped(confidence.get('level'))}, оценка {escaped(confidence.get('score'))}.
    Причины: {escaped(', '.join(confidence.get('reasons') or []))}.</p>
    {table(['Месяц', 'Очищенный спрос', 'Продажи', 'Исключено', 'Упущенный спрос',
            'Исходный вес', 'Нормализованный вес', 'Вклад в базу', 'Ячейка продажи'], selected_rows)}
    {details('Выбор окна и причины исключения месяцев',
             table(['Месяц', 'Очищенный спрос', 'Выбран', 'Причина'], window_rows))}
    {details('Факторы уверенности', f'<pre>{json_block(confidence.get("factors") or {})}</pre>')}
    </section>"""

    trend = s3.get("trend") or {}
    season = s3.get("seasonality") or {}
    trend_rows = [[item.get("period"), item.get("clean_demand"),
                   item.get("seasonality_index"), item.get("deseasonalized_demand"),
                   source_cell(source_files.get("sales") or {},
                               (item.get("source_cells") or {}).get("sales"))]
                  for item in trend.get("evidence") or []]
    season_rows = [[month, item.get("raw_index"), item.get("index"),
                    item.get("observation_count")]
                   for month, item in sorted((season.get("indices") or {}).items())]
    season_evidence_rows = [[item.get("period"), item.get("clean_demand"),
                             item.get("year_median"), item.get("ratio"),
                             source_cell(source_files.get("sales") or {},
                                         (item.get("source_cells") or {}).get("sales"))]
                            for _, evidence in sorted((season.get("evidence") or {}).items())
                            for item in evidence]
    forecast_rows = [[item.get("month"), item.get("base_demand"),
                      item.get("steps_from_base_month"), item.get("trend_adjustment"),
                      item.get("target_seasonality_index"),
                      item.get("base_window_seasonality_index"),
                      item.get("seasonality_multiplier"),
                      item.get("seasonality_adjustment"), item.get("final_forecast"),
                      item.get("reason")]
                     for item in s3.get("forecast_months") or []]
    stage3 = f"""<section id="stage3"><h2>3. Тренд, сезонность и помесячный прогноз</h2>
    <p>Тренд: {escaped(trend.get('status'))}; причина: {escaped(trend.get('reason'))};
    устойчивый наклон: {escaped(trend.get('slope_per_month'))} {escaped(unit)} / месяц.
    Сезонность: {escaped(season.get('status'))}.
    Прогноз месяца = max(0, max(0, база + ограниченная поправка тренда)
    + поправка сезонности); поправка сезонности = спрос после тренда ×
    (множитель сезона − 1).</p>
    {table(['Месяц прогноза', 'База', 'Шагов от базы', 'Поправка тренда',
            'Индекс сезона', 'Индекс базового окна', 'Множитель сезона',
            'Поправка сезона', 'Итоговый прогноз', 'Основание'], forecast_rows)}
    {details('Доказательства тренда по месяцам',
             table(['Месяц', 'Очищенный спрос', 'Индекс сезона', 'Без сезонности',
                    'Ячейка продажи'], trend_rows))}
    {details('Сезонные индексы',
             table(['Месяц года', 'Исходный индекс', 'Применённый индекс',
                    'Наблюдений'], season_rows))}
    {details('Наблюдения, из которых получены сезонные индексы',
             table(['Период', 'Очищенный спрос', 'Медиана года', 'Отношение',
                    'Ячейка продажи'], season_evidence_rows))}
    {details('Исходные периоды сезонности и дополнительные параметры',
             f'<pre>{json_block({"trend": trend, "seasonality": season})}</pre>')}
    </section>"""

    horizon_rows = [[item.get("month"), item.get("covered_start"),
                     item.get("covered_end_exclusive"), item.get("covered_days"),
                     item.get("days_in_month"), item.get("monthly_forecast"),
                     item.get("daily_forecast"), item.get("demand_contribution")]
                    for item in s4.get("forecast_months_in_lead_time") or []]
    stage4 = f"""<section id="stage4"><h2>4. Срок поставки и необходимый запас</h2>
    <p>Дата расчёта: {escaped(s4.get('planning_date'))}. Срок поставки:
    {escaped(s4.get('lead_time_days'))} дней ({escaped(s4.get('lead_time_source'))}).
    Горизонт до {escaped(s4.get('horizon_end_exclusive'))} без включения конечной даты.
    Срок поставки и дни страхового запаса заданы для сценария, а не взяты из договора поставщика.</p>
    {table(['Месяц', 'С', 'До (не включая)', 'Дней', 'Дней в месяце',
            'Прогноз / месяц', 'Прогноз / день', 'Вклад в спрос'], horizon_rows)}
    <p>Спрос за срок поставки: <strong>{escaped(s4.get('lead_time_demand'))}</strong>.
    Страховой запас: {escaped(s4.get('safety_stock_days'))} дней ×
    {escaped(s4.get('average_daily_forecast'))} {escaped(unit)} / день =
    <strong>{escaped(s4.get('safety_stock'))}</strong>
    ({escaped(s4.get('safety_stock_method'))}).<br>
    Необходимый запас = спрос за срок + страховой запас =
    <strong>{escaped(s4.get('target_stock'))} {escaped(unit)}</strong>.
    Статус: {escaped(s4.get('status'))}; причины недоступности:
    {escaped(', '.join(s4.get('unavailable_reasons') or []))}.</p></section>"""

    stage5 = f"""<section id="stage5"><h2>5. Актуальный остаток, путь и дефицит</h2>
    <p>Дата: {escaped(s5.get('planning_date'))}. Статус: {escaped(s5.get('status'))}.
    Для ответа нужны датированные текущие значения от пользователя или сверенного источника.
    Пользовательский ввод не сверяется автоматически с 1С или складом.</p>
    {source_evidence('Остаток, использованный в расчёте', s5.get('current_stock'))}
    {source_evidence('Товар в пути, использованный в расчёте', s5.get('goods_in_transit'))}
    {details('Исходные и заменённые значения из Excel',
             source_evidence('Исходный остаток', s5.get('source_current_stock'))
             + source_evidence('Исходный товар в пути', s5.get('source_goods_in_transit'))
             + source_evidence('Исторический месячный остаток', s5.get('historical_stock')))}
    <p>Сырой дефицит = необходимый запас {escaped(s5.get('target_stock'))} −
    текущий остаток {escaped((s5.get('current_stock') or {}).get('quantity'))} −
    товар в пути {escaped((s5.get('goods_in_transit') or {}).get('quantity'))} =
    <strong>{escaped(s5.get('raw_deficit'))} {escaped(unit)}</strong>.
    Потребность = max(0, сырой дефицит) = <strong>{escaped(s5.get('deficit'))}</strong>.
    Причины недоступности: {escaped(', '.join(s5.get('unavailable_reasons') or []))}.
    Причины условности: {escaped(', '.join(s5.get('provisional_reasons') or []))}.</p>
    </section>"""

    rule = s6.get("packing_rule") or {}
    kind = rule.get("rule_kind")
    rule_description = {
        "multiple": "Кратность: положительную потребность округлить вверх до ближайшего кратного числа.",
        "minimum_dispatch": "Минимальная отгрузка: округлить положительную потребность до целой единицы и взять максимум с минимумом.",
    }.get(kind, "Правило поставщика не подтверждено; размер заказа не вычисляется при положительной потребности.")
    urgency_text = {
        "HIGH": "HIGH — текущий остаток ниже спроса за срок поставки.",
        "MEDIUM": "MEDIUM — срок поставки покрыт, но не хватает до страхового запаса.",
        "LOW": "LOW — необходимый запас покрыт.",
    }.get(s6.get("urgency"), "Срочность не определена.")
    status_notice = {
        "provisional": "Условный результат: проверьте указанные ниже причины до решения о закупке.",
        "unavailable": "Результат недоступен: неизвестные значения не заменены нулём.",
    }.get(s6.get("status"), "Расчёт выполнен по указанным входным данным.")
    stage6 = f"""<section id="stage6"><h2>6. Нужно ли закупать, сколько и насколько срочно</h2>
    <p class="notice"><strong>{escaped(status_notice)}</strong></p>
    <p>Нужно закупать: <strong>{escaped(s6.get('purchase_needed'))}</strong>.
    Правило: {escaped(kind)}; значение {escaped(rule.get('quantity'))};
    статус {escaped(rule.get('status'))}. {escaped(rule_description)}</p>
    {table(['Параметр правила', 'Значение'], [
        ['Источник', source_refs(rule.get('source_refs'))],
        ['Замечания', ', '.join(rule.get('notes') or [])],
    ])}
    <p>Сырой дефицит: {escaped(s6.get('raw_deficit'))}; положительная потребность:
    {escaped(s6.get('deficit'))}; рекомендуемый заказ:
    <strong>{escaped(s6.get('recommended_order'))} {escaped(unit)}</strong>.
    Срочность: <strong>{escaped(s6.get('urgency'))}</strong>. {escaped(urgency_text)}
    Основание риска: текущий остаток {escaped((s6.get('current_stock') or {}).get('quantity'))}
    против спроса за срок {escaped(s6.get('lead_time_demand'))}.</p>
    {table(['Поле', 'Значение'], [
        ['Статус рекомендации', s6.get('status')],
        ['Статус дефицита', s6.get('deficit_status')],
        ['Причины рекомендации', ', '.join(s6.get('reasons') or [])],
        ['Причины срочности', ', '.join(s6.get('urgency_reasons') or [])],
        ['Замечания к вводу', '\n'.join(s6.get('input_notes') or [])],
    ])}
    <p class="notice">Количество — черновая рекомендация. Утверждение заказа остаётся за человеком.</p>
    </section>"""

    summary = f"""<header><p class="eyebrow">Трассировка расчёта по одному артикулу</p>
    <h1>Как получен результат: {escaped(brand)} / {escaped(sku)}</h1>
    <p>{escaped(name)} · {escaped(unit)} · дата планирования {escaped(trace.get('planning_date') or s6.get('planning_date'))}</p>
    <div class="cards">
      <div class="card"><span>Базовый спрос / месяц</span><b>{escaped(s2.get('base_demand_monthly'))}</b></div>
      <div class="card"><span>Необходимый запас</span><b>{escaped(s4.get('target_stock'))}</b></div>
      <div class="card"><span>Текущий остаток</span><b>{escaped((s5.get('current_stock') or {}).get('quantity'))}</b></div>
      <div class="card"><span>В пути</span><b>{escaped((s5.get('goods_in_transit') or {}).get('quantity'))}</b></div>
      <div class="card"><span>Сырой дефицит</span><b>{escaped(s5.get('raw_deficit'))}</b></div>
      <div class="card"><span>Заказать</span><b>{escaped(s6.get('recommended_order'))}</b></div>
    </div><nav aria-label="Этапы расчёта"><a href="#stage1">Продажи</a><a href="#stage2">База</a>
    <a href="#stage3">Прогноз</a><a href="#stage4">Запас</a><a href="#stage5">Дефицит</a>
    <a href="#stage6">Заказ</a></nav></header>"""
    lineage = trace.get("lineage") or {}
    provenance = f"""<section><h2>Происхождение и воспроизводимость</h2>
    <p>Исходный Git-коммит: <code>{escaped(trace.get('source_commit'))}</code>.</p>
    <p>Хеши входов фиксируют версию каждого промежуточного файла. Изменение ввода
    пользователя требует нового расчёта, а не ручной правки результата.</p>
    <pre>{json_block(lineage)}</pre></section>"""
    raw = "".join(details(f"Полная запись этапа {number} (JSON)",
                          f'<pre>{json_block(stages[number])}</pre>')
                  for number in range(1, 7))
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Как получен результат — {escaped(brand)} / {escaped(sku)}</title>
    <style>
    :root{{color-scheme:light}}*{{box-sizing:border-box}}
    body{{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#17342d;
    background:#fafbf9;margin:0}}main{{max-width:1300px;margin:auto;padding:28px 26px 64px}}
    h1{{font-size:clamp(25px,3vw,38px);line-height:1.16;margin:5px 0 8px}}
    h2{{font-size:23px;margin:0 0 15px}}h3{{font-size:17px;margin:24px 0 10px}}
    p{{margin:10px 0 16px}}.eyebrow{{text-transform:uppercase;letter-spacing:.08em;
    color:#60776d;font-size:12px;font-weight:700}}section{{background:white;border:1px solid #dce5df;
    border-radius:10px;padding:24px;margin:20px 0}}header{{padding:18px 0 12px}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px;margin:24px 0}}
    .card{{background:white;border:1px solid #dce5df;border-radius:8px;padding:14px}}
    .card span{{display:block;font-size:12px;color:#60776d}}.card b{{display:block;font-size:22px;margin-top:5px}}
    nav{{display:flex;gap:10px;flex-wrap:wrap}}nav a{{color:#135b48;background:#e9f2ec;
    text-decoration:none;padding:6px 10px;border-radius:6px}}.table-wrap{{overflow:auto}}
    table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
    th,td{{border-bottom:1px solid #e7ede8;padding:8px 10px;text-align:left;
    vertical-align:top;white-space:pre-wrap;min-width:75px}}th{{background:#f3f7f4;font-size:12px}}
    details{{border:1px solid #e0e8e2;border-radius:7px;margin:15px 0;padding:9px 12px}}
    summary{{cursor:pointer;font-weight:600}}details .table-wrap,details pre{{margin-top:10px}}
    pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f5;padding:13px;border-radius:6px}}
    code{{overflow-wrap:anywhere}}.notice{{background:#fff6df;border-left:3px solid #dca24b;padding:11px}}
    @media print{{body{{background:white}}main{{max-width:none}}section{{break-inside:avoid}}}}
    </style></head><body><main>{summary}{stage1}{stage2}{stage3}{stage4}{stage5}{stage6}
    {provenance}<section><h2>Полные промежуточные записи</h2>
    <p>Исходные поля этапов сохранены без выборки и округления. Раскройте запись для проверки.</p>
    {raw}</section></main></body></html>"""
    path.write_text(page, encoding="utf-8")

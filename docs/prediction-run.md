# Запуск расчётной части

Работать из корня проекта. После интеграции с `main` нормализованный JSON можно отправить в `POST /api/planning-runs`. Установка:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
npm ci --prefix frontend
```

Реальные данные IEK, 50 SKU; все результаты локальные:

```powershell
.venv\Scripts\python -m backend.cli --data-dir data --output outputs/iek-planning-result.json --limit 50
.venv\Scripts\python -m backend.evaluation --input outputs/iek-planning-result.input.json --output outputs/iek-evaluation.json
```

CLI также принимает --lead-time-days, --review-period-days, --safety-stock-days.
JSON включает прогноз на горизонт, страховой запас, остаток, допустимый транзит,
заказ, flags, diagnostics и assumptions. В audit.json указаны источники и исключения.
input.json можно повторно подать через --input. Функция интеграции:

```python
from backend.planning import plan
from backend.ai import explain

result = plan(planning_input)
row = result["recommendations"][0]
explanation = explain(row, data_source=result["data_source"])
```

## OpenAI

Серверная конфигурация: OPENAI_API_KEY и OPENAI_MODEL.
Выбрана [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
фиксированный snapshot `gpt-4.1-mini-2025-04-14`: Responses API, Structured Outputs.
Модель можно переопределить через OPENAI_MODEL. CLI автоматически читает .env из
корня репозитория, сохраняя приоритет переменных процесса. При прямом вызове
explain из другого backend ключ передаётся через окружение вызывающего процесса.

```powershell
$env:OPENAI_MODEL = "gpt-4.1-mini-2025-04-14"
# OPENAI_API_KEY задаётся только локально, не в Git и не во frontend.
.venv\Scripts\python -m backend.cli --input fixtures/planning-input.sample.json --output outputs/synthetic-result.json --explain-sku CABLE-01
```

Ответ explanation.json: summary, drivers, risk, review_question, evidence_keys,
fallback, fallback_reason, model. Модель выбирает значимые факторы; тексты и
числа формирует сервер из закрытого словаря. Это ограничивает вымышленные факты.
Без конфигурации или при сбое возвращается fallback. Для партнёрского источника
по умолчанию API-вызов заблокирован; allow_partner_data=True разрешён только
после отдельного согласования отправки агрегатов. CLI такого флага не предоставляет.

Реальный вызов Responses API проверен 23.09.2026 на синтетической фикстуре:
status=completed, fallback=false, модель gpt-4.1-mini-2025-04-14.
Локальный результат: outputs/openai-live-check.json. Ключ хранится только в
игнорируемом .env и не включается в коммиты. Обвязка дополнительно проверена
имитациями таймаута, невалидного ответа и отказа/незавершённого ответа.

## Проверка и границы

```powershell
.venv\Scripts\python scripts/check.py
```

Проверяются Ruff, mypy, pytest, типы контрактов, frontend lint/typecheck/test/build.
HTTP-маршрут вызывает `plan`; UI и адаптер AI-объяснения ещё проверяются отдельно.
Функции select_quantity/approve сохраняют ручной контроль.

Контракт входа расширен до 0.2.0: monthly_history, document_id, необязательная
цена, дата/источник остатка, ETA, metadata. Старые фикстуры валидны.
Выходной mock не изменён: добавлены только необязательные диагностические поля
в схему и перегенерированы TypeScript-типы.

## Измерение качества

На 50 отобранных SKU, последние три полных месяца (июнь–август 2026), 150 точек:
автоматический выбор методов показал WAPE 33.67%, среднее последних шести
наблюдений — 32.90%. WAPE = сумма абсолютных ошибок / сумма фактических продаж.
Преимущество автоматического выбора **не подтверждено**. Эти проценты не являются
вероятностью правильного прогноза. Оценка ограничена отобранными SKU и тремя месяцами.
После этого измерения модели не подстраивались под отложенные месяцы.

Для решения о закупке необходимо подтвердить актуальные остатки, охват складов,
срок поставки, MOQ/кратность и правила для корректировок. Текущий результат —
проверяемый сценарный черновик.

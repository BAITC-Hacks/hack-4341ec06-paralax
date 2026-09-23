# Запуск расчётной части

Работать из корня ветки feat/alikt/prediction. Установка:

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

Серверная конфигурация: OPENAI_API_KEY и OPENAI_MODEL. Модель явно задаёт команда
из доступных её API-проекту моделей с поддержкой Structured Outputs.
Файл .env сам по себе не загружается: установите переменные окружения процесса.

```powershell
$env:OPENAI_MODEL = "доступная-в-вашем-проекте-модель"
# OPENAI_API_KEY задаётся только локально, не в Git и не во frontend.
.venv\Scripts\python -m backend.cli --input fixtures/planning-input.sample.json --output outputs/synthetic-result.json --explain-sku CABLE-01
```

Ответ explanation.json: summary, drivers, risk, review_question, evidence_keys,
fallback, fallback_reason, model. Модель выбирает значимые факторы; тексты и
числа формирует сервер из закрытого словаря. Это ограничивает вымышленные факты.
Без конфигурации или при сбое возвращается fallback. Для партнёрского источника
по умолчанию API-вызов заблокирован; allow_partner_data=True разрешён только
после отдельного согласования отправки агрегатов. CLI такого флага не предоставляет.

Реальный вызов API в этой сессии не выполнялся. Обвязка проверена имитациями
успеха, таймаута, невалидного ответа и отказа/незавершённого ответа.

## Проверка и границы

```powershell
.venv\Scripts\python scripts/check.py
```

Проверяются Ruff, mypy, pytest, типы контрактов, frontend lint/typecheck/test/build.
HTTP-маршруты и UI не реализуются этой частью; интегратор вызывает plan/explain.
Функции select_quantity/approve сохраняют ручной контроль.

Контракт входа расширен до 0.2.0: monthly_history, document_id, необязательные
customer_id/цена, дата/источник остатка, ETA, metadata. Старые фикстуры валидны.
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

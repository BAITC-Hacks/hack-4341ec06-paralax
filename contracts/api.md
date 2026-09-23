# HTTP API для MVP

Backend: `backend/app.py`, локальный запуск `python -m uvicorn backend.app:app --reload`. JSON-схемы в этой папке — источник истины для тела `PlanningInput`, `PlanningResult` и `RecommendationExplanation`. Временное хранилище черновиков находится в памяти процесса; после перезапуска сервера они исчезают. Авторизация и отправка заказа поставщику в MVP не предусмотрены.

## Маршруты

- `GET /api/health` → `status`, `planner_ready`, `ai_ready`. `planner_ready` показывает подключение расчёта; `ai_ready` — наличие адаптера AI в HTTP-слое, а не доступность OpenAI API.
- `GET /api/demo/planning-input` → синтетический вход для отладки.
- `POST /api/demo/planning-runs` → новый черновик из синтетического `fixtures/planning-result.demo.json`. Числа здесь подготовлены вручную для UI и **не являются ответом алгоритма**.
- `POST /api/planning-runs` принимает `PlanningInput`, проверяет JSON Schema и ссылки между SKU/поставщиками, вызывает `backend.planning.plan(input)` и возвращает `PlanningResult` со статусом `draft`. Модуль расчёта подключён. Ошибки входа — `422`, `detail.errors[]` с полем `field` и причиной `reason`.
- `GET /api/planning-runs/{run_id}` → сохранённый черновик/утверждённый результат, `404` если ID нет.
- `PATCH /api/planning-runs/{run_id}/recommendations/{sku}` принимает `{ "selected_quantity": integer >= 0 }`. Меняет только выбранное количество в `draft`; `recommended_quantity` сохраняется. Для утверждённого результата — `409`.
- `POST /api/planning-runs/{run_id}/approve` явно утверждает черновик. Повторное утверждение идемпотентно и не отправляет заказ.
- `POST /api/planning-runs/{run_id}/recommendations/{sku}/explanation` пока возвращает детерминированное объяснение с `source: "fallback"`. Модуль `backend.ai.explain` из ветки данных имеет иной формат ответа и ещё требует отдельного адаптера с проверкой схемы и разрешения на передачу данных.
- `GET /api/planning-runs/{run_id}/export` возвращает CSV в UTF-8 с BOM, отсортированный по поставщику и SKU. В нём указаны исходное и выбранное количество, статус и дата расчёта. Текстовые ячейки защищены от выполнения формул в Excel.

## Граница между участниками

`backend.planning.plan(planning_input: dict) -> dict` возвращает объект по `planning-result.schema.json` и вызывается HTTP-маршрутом. `backend.importers.iek.import_iek(data_dir)` возвращает нормализованный вход и аудит; текущий запуск импорта выполняется через CLI, после чего JSON передаётся в API. `backend.ai.explain` доступен для локальных синтетических проверок, но его ответ ещё не приведён к `explanation.schema.json`, поэтому HTTP-слой его не вызывает. Внешний OpenAI API не вызывается при расчёте, ручной правке или экспорте.

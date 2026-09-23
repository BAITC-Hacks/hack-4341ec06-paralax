# HTTP API для MVP

Backend: `backend/app.py`, локальный запуск `python -m uvicorn backend.app:app --reload`. JSON-схемы в этой папке — источник истины для тела `PlanningInput`, `PlanningResult` и `RecommendationExplanation`. Временное хранилище черновиков находится в памяти процесса; после перезапуска сервера они исчезают. Авторизация и отправка заказа поставщику в MVP не предусмотрены.

## Маршруты

- `GET /api/health` → `status`, `planner_ready`, `ai_ready`. Флаги показывают наличие модулей команды, а не доступность внешнего OpenAI API.
- `GET /api/demo/planning-input` → синтетический вход для отладки.
- `POST /api/demo/planning-runs` → новый черновик из синтетического `fixtures/planning-result.demo.json`. Числа здесь подготовлены вручную для UI и **не являются ответом алгоритма**.
- `POST /api/planning-runs` принимает `PlanningInput`, проверяет JSON Schema и ссылки между SKU/поставщиками, вызывает `backend.planning.plan(input)` и возвращает `PlanningResult` со статусом `draft`. Пока модуль расчёта не добавлен участником данных, возвращает `503` с кодом `planner_not_ready`. Ошибки входа — `422`, `detail.errors[]` с полем `field` и причиной `reason`.
- `GET /api/planning-runs/{run_id}` → сохранённый черновик/утверждённый результат, `404` если ID нет.
- `PATCH /api/planning-runs/{run_id}/recommendations/{sku}` принимает `{ "selected_quantity": integer >= 0 }`. Меняет только выбранное количество в `draft`; `recommended_quantity` сохраняется. Для утверждённого результата — `409`.
- `POST /api/planning-runs/{run_id}/approve` явно утверждает черновик. Повторное утверждение идемпотентно и не отправляет заказ.
- `POST /api/planning-runs/{run_id}/recommendations/{sku}/explanation` вызывает `backend.ai.explain(recommendation)` после подключения модуля. Возвращает `RecommendationExplanation`; при отсутствии модуля, ошибке, неподтверждённых числах или нарушении схемы — детерминированный ответ с `source: "fallback"`.
- `GET /api/planning-runs/{run_id}/export` возвращает CSV в UTF-8 с BOM, отсортированный по поставщику и SKU. В нём указаны исходное и выбранное количество, статус и дата расчёта. Текстовые ячейки защищены от выполнения формул в Excel.

## Граница между участниками

Участник данных предоставляет синхронные функции `backend.planning.plan(planning_input: dict) -> dict` и `backend.ai.explain(recommendation: dict) -> dict`. `plan` возвращает объект по `planning-result.schema.json`; `explain` — объект по `explanation.schema.json` без обязательного `source` (API проставит `openai`). Импорт `backend.ai` не должен требовать наличия API-ключа: клиент создаётся при вызове, а отсутствие ключа обрабатывается резервным ответом. Он не меняет `backend/app.py`. API-код не читает реальные Excel и не отправляет данные в OpenAI самостоятельно. Для изменения этого соглашения сначала обновить контракт и приёмочные тесты.

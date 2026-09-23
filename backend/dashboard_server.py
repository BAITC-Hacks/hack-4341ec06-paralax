"""Local, read-only-source dashboard API for the Stage-8 planning UI.

Run from the repository root: ``python backend/dashboard_server.py``.
Stock entered in the browser is held in this process only; it never changes a
partner workbook or a saved Stage-1..6 result in .analysis/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from apply_stock_inputs import apply_overrides, require_as_of_date, require_quantity
from deficit import calculate_deficit
from order_recommendation import calculate_order, file_hash, load_jsonl
from trace_page import render_trace_html
from trace_sku import DEFAULT_INPUTS, assemble_trace, load_selected

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_ORIGINS = {
    "http://127.0.0.1:5173", "http://localhost:5173",
    "http://127.0.0.1:5174", "http://localhost:5174",
    "http://127.0.0.1:5176", "http://localhost:5176",
}


def paths_for_scenario(root: Path, scenario: str) -> dict[str, Path]:
    if scenario not in ("source-snapshot", "demo-user-input"):
        raise ValueError(f"Unknown scenario: {scenario}")
    paths = {name: root / path for name, path in DEFAULT_INPUTS.items()}
    if scenario == "demo-user-input":
        paths["stage5"] = root / ".analysis/deficit/demo-user-input/all-skus.jsonl"
        paths["stage6"] = root / ".analysis/orders/demo-user-input/all-skus.jsonl"
        paths["balances"] = root / ".analysis/balances/demo-user-input.jsonl"
    return paths


def record_hash(record: dict) -> str:
    """Hash one canonical in-memory record, not an on-disk JSONL file."""
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_row(order: dict, target: dict) -> dict:
    rule = order.get("packing_rule") or {}
    stock = order.get("current_stock") or {}
    transit = order.get("goods_in_transit") or {}
    forecast_months = target.get("forecast_months_in_lead_time") or []
    first_forecast = forecast_months[0].get("monthly_forecast") if forecast_months else None
    return {
        "brand": order["brand"], "sku": order["sku"],
        "name": order.get("name") or target.get("name") or "",
        "unit": order.get("unit") or target.get("unit"),
        "current_stock": stock.get("quantity"),
        "goods_in_transit": transit.get("quantity"),
        "forecast": target.get("lead_time_demand"),
        "monthly_forecast": first_forecast,
        "target_stock": order.get("target_stock"),
        "recommended_order": order.get("recommended_order"),
        "purchase_needed": order.get("purchase_needed"),
        "urgency": order.get("urgency"), "status": order.get("status"),
        "stock_quality": stock.get("quality"),
        "transit_quality": transit.get("quality"),
        "rule_kind": rule.get("rule_kind"),
        "rule_quantity": rule.get("quantity"),
        "lead_time_demand": target.get("lead_time_demand"),
        "safety_stock": target.get("safety_stock"),
        "raw_deficit": order.get("raw_deficit"),
        "deficit": order.get("deficit"),
        "reasons": order.get("reasons") or [],
    }


class _HtmlSink:
    def __init__(self) -> None:
        self.value = ""

    def write_text(self, value: str, encoding: str = "utf-8") -> None:
        self.value = value


class DashboardData:
    """Loaded source snapshot plus process-local, per-SKU user scenarios."""

    def __init__(self, root: Path = REPO_ROOT, scenario: str = "source-snapshot") -> None:
        self.paths = paths_for_scenario(root, scenario)
        for name, path in self.paths.items():
            if not path.is_file():
                raise FileNotFoundError(f"Missing {name} source: {path}")
        self.scenario = scenario
        self.targets = load_jsonl(self.paths["stage4"], "Stage 4")
        self.deficits = load_jsonl(self.paths["stage5"], "Stage 5")
        self.orders = load_jsonl(self.paths["stage6"], "Stage 6")
        self.balances = load_jsonl(self.paths["balances"], "balances")
        self.rules = load_jsonl(self.paths["rules"], "rules")
        keys = set(self.orders)
        if keys != set(self.targets) or keys != set(self.deficits) or keys != set(self.balances):
            raise ValueError("Stage-4/5/6 and balance SKU sets differ")
        dates = {row.get("planning_date") for row in self.orders.values()}
        if len(dates) != 1 or None in dates:
            raise ValueError("Planning dates differ across Stage-6 rows")
        self.planning_date = dates.pop()
        self.hashes = {name: file_hash(path) for name, path in self.paths.items()}
        self.overrides: dict[tuple[str, str], tuple[dict, dict, dict]] = {}
        self.lock = threading.RLock()

    def dashboard(self) -> dict:
        with self.lock:
            rows = [project_row(self.overrides[key][2] if key in self.overrides else self.orders[key],
                                self.targets[key]) for key in sorted(self.orders)]
            override_count = len(self.overrides)
        return {
            "planning_date": self.planning_date,
            "source_kind": "source_snapshot",
            "scenario_kind": ("illustrative_user_input" if self.scenario == "demo-user-input"
                              else "source_snapshot"),
            "session_overrides": override_count,
            "rows": rows,
        }

    def update_stock(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        required = {"brand", "sku", "current_stock", "goods_in_transit", "as_of_date"}
        if set(payload) != required:
            raise ValueError("Expected brand, sku, current_stock, goods_in_transit, as_of_date")
        brand, sku = payload["brand"], payload["sku"]
        if not isinstance(brand, str) or not isinstance(sku, str):
            raise ValueError("brand and sku must be strings")
        key = (brand, sku)
        if key not in self.orders:
            raise KeyError(f"Unknown brand/SKU: {brand} / {sku}")
        stock = require_quantity(payload["current_stock"], "current_stock")
        transit = require_quantity(payload["goods_in_transit"], "goods_in_transit")
        as_of_date = require_as_of_date(payload["as_of_date"])
        balance = apply_overrides(self.balances[key], as_of_date,
                                  {key: stock}, {key: transit})
        balance_sha = record_hash(balance)
        deficit = calculate_deficit(self.targets[key], balance,
                                    self.hashes["stage4"], balance_sha)
        order = calculate_order(deficit, self.targets[key], self.rules.get(key),
                                deficit_sha256=record_hash(deficit),
                                rules_sha256=self.hashes["rules"])
        with self.lock:
            self.overrides[key] = (balance, deficit, order)
        return {"row": project_row(order, self.targets[key]),
                "scenario_kind": "session_user_input"}

    def trace_html(self, brand: str, sku: str) -> str:
        key = (brand, sku)
        if key not in self.orders:
            raise KeyError(f"Unknown brand/SKU: {brand} / {sku}")
        with self.lock:
            override = self.overrides.get(key)
        stages = {}
        hashes = dict(self.hashes)
        for number in range(1, 5):
            name = f"stage{number}"
            selected, actual_hash = load_selected(self.paths[name], {key}, name)
            if actual_hash != hashes[name] or key not in selected:
                raise ValueError(f"{name} changed or lacks {brand} / {sku}")
            stages[name] = selected[key]
        if override is None:
            balance = self.balances[key]
            stages["stage5"] = self.deficits[key]
            stages["stage6"] = self.orders[key]
        else:
            balance, stages["stage5"], stages["stage6"] = override
            hashes["balances"] = record_hash(balance)
            hashes["stage5"] = record_hash(stages["stage5"])
            hashes["stage6"] = record_hash(stages["stage6"])
        trace = assemble_trace(stages, hashes, balance, self.rules.get(key))
        if override is not None:
            trace["lineage"]["scenario_kind"] = "session_user_input"
            trace["lineage"]["hash_scope"] = {
                "balances": "canonical_in_memory_record",
                "stage5": "canonical_in_memory_record",
                "stage6": "canonical_in_memory_record",
            }
        sink = _HtmlSink()
        render_trace_html(trace, sink)
        if override is not None:
            notice = ('<aside class="notice"><strong>Сценарий с вводом пользователя.</strong> '
                      'Значения хранятся только в этой локальной сессии; хеши баланса '
                      'и этапов 5–6 относятся к записям в памяти, не к файлам JSONL. '
                      'Складские данные не сверены автоматически.</aside>')
            return sink.value.replace("<main>", "<main>" + notice, 1)
        return sink.value


def make_handler(data: DashboardData):
    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin in ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: dict) -> None:
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _origin_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            return origin is None or origin in ALLOWED_ORIGINS

        def do_OPTIONS(self) -> None:
            if not self._origin_allowed():
                self._json(403, {"error": "Origin is not allowed"})
                return
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            route = urlsplit(self.path)
            if not self._origin_allowed():
                self._json(403, {"error": "Origin is not allowed"})
                return
            try:
                if route.path == "/api/dashboard":
                    self._json(200, data.dashboard())
                elif route.path == "/api/trace":
                    query = parse_qs(route.query, keep_blank_values=True)
                    if set(query) != {"brand", "sku"} or any(len(v) != 1 for v in query.values()):
                        raise ValueError("Specify one brand and one sku")
                    page = data.trace_html(query["brand"][0], query["sku"][0])
                    self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                else:
                    self._json(404, {"error": "Not found"})
            except KeyError as error:
                self._json(404, {"error": str(error)})
            except ValueError as error:
                self._json(400, {"error": str(error)})

        def do_POST(self) -> None:
            if not self._origin_allowed():
                self._json(403, {"error": "Origin is not allowed"})
                return
            if urlsplit(self.path).path != "/api/stock":
                self._json(404, {"error": "Not found"})
                return
            try:
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                    raise ValueError("Content-Type must be application/json")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16_384:
                    raise ValueError("JSON body size must be 1–16384 bytes")
                payload = json.loads(self.rfile.read(length))
                self._json(200, data.update_stock(payload))
            except KeyError as error:
                self._json(404, {"error": str(error)})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("source-snapshot", "demo-user-input"),
                        default="source-snapshot")
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()
    data = DashboardData(scenario=args.scenario)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(data))
    print(f"Dashboard API: http://127.0.0.1:{server.server_port}/api/dashboard "
          f"({len(data.orders)} SKUs; {args.scenario})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

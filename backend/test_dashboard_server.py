"""Behavior checks for the local Stage-8 dashboard adapter."""

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dashboard_server import DashboardData, make_handler, record_hash
from test_trace_sku import fixture


def synthetic_data(stock=4):
    stages, hashes, balance, rule = fixture(stock)
    key = (stages["stage4"]["brand"], stages["stage4"]["sku"])
    data = DashboardData.__new__(DashboardData)
    data.targets = {key: stages["stage4"]}
    data.deficits = {key: stages["stage5"]}
    data.orders = {key: stages["stage6"]}
    data.balances = {key: balance}
    data.rules = {key: rule}
    data.hashes = hashes
    data.planning_date = "2026-09-01"
    data.scenario = "source-snapshot"
    data.overrides = {}
    data.lock = threading.RLock()
    return data, key


class DashboardTests(unittest.TestCase):
    def test_null_stock_stays_unknown_in_dashboard(self):
        data, _ = synthetic_data(None)
        row = data.dashboard()["rows"][0]
        self.assertIsNone(row["current_stock"])
        self.assertIsNone(row["purchase_needed"])
        self.assertIsNone(row["recommended_order"])
        self.assertEqual(row["status"], "unavailable")
        self.assertEqual(row["forecast"], 12)
        self.assertEqual(row["monthly_forecast"], 12)

    def test_user_input_recalculates_only_selected_sku_without_changing_source(self):
        data, key = synthetic_data()
        source_order = data.orders[key]
        response = data.update_stock({
            "brand": key[0], "sku": key[1], "current_stock": 13,
            "goods_in_transit": 1, "as_of_date": "2026-09-01",
        })
        row = response["row"]
        self.assertEqual(row["current_stock"], 13)
        self.assertEqual(row["raw_deficit"], 1)
        self.assertEqual(row["recommended_order"], 6)
        self.assertEqual(row["stock_quality"], "confirmed_current")
        self.assertEqual(response["scenario_kind"], "session_user_input")
        self.assertEqual(source_order["recommended_order"], 12)
        self.assertEqual(data.dashboard()["session_overrides"], 1)
        self.assertEqual(data.overrides[key][1]["balance_sha256"],
                         record_hash(data.overrides[key][0]))

    def test_stale_user_date_is_provisional_and_bad_numbers_are_rejected(self):
        data, key = synthetic_data()
        payload = {"brand": key[0], "sku": key[1], "current_stock": 4,
                   "goods_in_transit": 1, "as_of_date": "2026-08-31"}
        row = data.update_stock(payload)["row"]
        self.assertEqual(row["status"], "provisional")
        self.assertIsNone(row["recommended_order"])
        for invalid in (-1, True, float("nan"), None, 2**53):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                data.update_stock({**payload, "current_stock": invalid})

    def test_projection_preserves_zero_order(self):
        data, key = synthetic_data()
        row = data.update_stock({"brand": key[0], "sku": key[1],
                                 "current_stock": 20, "goods_in_transit": 0,
                                 "as_of_date": "2026-09-01"})["row"]
        self.assertIs(row["purchase_needed"], False)
        self.assertEqual(row["recommended_order"], 0)
        self.assertEqual(row["status"], "calculated")

    def test_preview_origin_can_post_but_other_origin_cannot(self):
        data, key = synthetic_data()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(data))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        body = json.dumps({"brand": key[0], "sku": key[1], "current_stock": 4,
                           "goods_in_transit": 1,
                           "as_of_date": "2026-09-01"}).encode("utf-8")
        url = f"http://127.0.0.1:{server.server_port}/api/stock"
        try:
            request = Request(url, body, {"Content-Type": "application/json",
                                          "Origin": "http://127.0.0.1:5174"}, method="POST")
            with urlopen(request) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Access-Control-Allow-Origin"],
                                 "http://127.0.0.1:5174")
            request = Request(url, body, {"Content-Type": "application/json",
                                          "Origin": "https://other.example"}, method="POST")
            with self.assertRaises(HTTPError) as rejected:
                urlopen(request)
            self.assertEqual(rejected.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

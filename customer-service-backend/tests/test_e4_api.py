"""E4 contract tests: no live network and no business writes."""
import unittest
from unittest.mock import patch
import httpx
from my_agent import api_client
from my_agent.tools import query_order_status

ORDER = "C20260406001"


def response(data, *, code=0, status=200):
    return httpx.Response(status, json={"code": code, "message": "ok", "data": data},
                          request=httpx.Request("GET", "http://test/orders"))


class TestAPIContracts(unittest.TestCase):
    def test_invalid_id_never_reaches_network(self):
        with patch("httpx.get") as get:
            with self.assertRaises(ValueError):
                api_client.get_order_status("../health")
            get.assert_not_called()

    def test_mismatched_order_is_rejected(self):
        with patch("httpx.get", return_value=response({
            "order_id": "A20260410001", "status": "待发货", "status_desc": "备货中"})):
            with self.assertRaises(ValueError):
                api_client.get_order_status(ORDER)

    def test_malformed_payload_is_rejected(self):
        for payload in [{}, {"order_id": ORDER, "status": 7, "status_desc": "x"}]:
            with self.subTest(payload=payload), patch("httpx.get", return_value=response(payload)):
                with self.assertRaises(ValueError):
                    api_client.get_order_status(ORDER)

    def test_tool_timeout_returns_safe_failure(self):
        with patch("httpx.get", side_effect=httpx.ReadTimeout("secret connection details")):
            result = query_order_status.invoke({"order_id": ORDER})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["kind"], "unavailable")
        self.assertNotIn("secret", str(result))

    def test_valid_status_and_list(self):
        with patch("httpx.get", return_value=response({
            "order_id": ORDER, "status": "待发货", "status_desc": "备货中"})):
            self.assertEqual(api_client.get_order_status(ORDER)["status"], "待发货")
        with patch("httpx.get", return_value=response({"user_id": "u1003", "orders": []})):
            self.assertEqual(api_client.get_user_orders("u1003")["orders"], [])

    def test_http_failures_are_classified(self):
        for status, kind in [(404, "not_found"), (409, "conflict"), (422, "invalid_request"), (503, "unavailable")]:
            with self.subTest(status=status), patch("httpx.get", return_value=response({}, status=status)):
                result = query_order_status.invoke({"order_id": ORDER})
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["kind"], kind)

    def test_bad_json_and_business_failure_are_safe(self):
        for reply in [httpx.Response(200, text="not json", request=httpx.Request("GET", "http://test")),
                      response({}, code=1), response({}, code=True)]:
            with self.subTest(reply=reply), patch("httpx.get", return_value=reply):
                result = query_order_status.invoke({"order_id": ORDER})
                self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()

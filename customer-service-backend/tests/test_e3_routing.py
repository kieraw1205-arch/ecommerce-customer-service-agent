"""E3-07：意图路由覆盖测试。"""

import unittest
from my_agent.routing import route_intent


class TestIntentRouting(unittest.TestCase):

    def test_all_intent_routes(self):
        cases = [
            ("order_list", {"user_id": "u1002"}, "query"),
            ("order_list", {}, "clarify"),
            ("order_status", {"order_id": "A20260410001"}, "query"),
            ("order_status", {}, "clarify"),
            ("logistics", {"order_id": "A20260410001"}, "logistics"),
            ("logistics", {}, "clarify"),
            ("shipping_reminder", {}, "business"),
            ("refund", {}, "business"),
            ("multi_intent", {}, "business"),
            ("product_qa", {}, "knowledge"),
            ("chitchat", {}, "chat"),
            ("cancel", {}, "cancel"),
            ("unclear", {}, "clarify"),
            ("unsupported", {}, "unsupported"),
        ]

        for intent, fields, expected in cases:
            with self.subTest(intent=intent, fields=fields):
                state = {
                    "intent_result": {
                        "intent": intent,
                        **fields,
                    }
                }
                self.assertEqual(
                    route_intent(state),
                    expected,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)

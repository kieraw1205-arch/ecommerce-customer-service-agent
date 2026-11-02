"""测试意图识别失败时的状态保护。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from my_agent.nodes import recognize_intent_node


class TestModelErrors(unittest.TestCase):

    @patch(
        "my_agent.nodes.recognize_intent",
        side_effect=TimeoutError("Qwen API timeout"),
    )
    def test_intent_timeout_preserves_workflow(self, mock_llm):
        workflow = {
            "status": "pending",
            "current_step": 0,
            "tasks": [
                {
                    "intent": "order_status",
                    "order_id": "A20260410001",
                    "status": "pending",
                }
            ],
        }

        result = recognize_intent_node({
            "messages": [
                HumanMessage(content="帮我查一下其他订单")
            ],
            "pending_intent": None,
            "pending_workflow": workflow,
        })

        self.assertEqual(
            result["intent_result"]["reason"],
            "intent_recognition_failed",
        )

        self.assertNotIn("pending_workflow", result)
        self.assertNotIn("pending_intent", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

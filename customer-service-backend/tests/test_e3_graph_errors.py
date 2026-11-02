"""E3-07：LangGraph 异常路由集成测试。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from my_agent.graph import graph


class TestGraphErrors(unittest.TestCase):

    @patch(
        "my_agent.nodes.recognize_intent",
        side_effect=TimeoutError("Qwen timeout"),
    )
    def test_graph_timeout_single_reply(self, mock_llm):
        config = {
            "configurable": {
                "thread_id": "e3-graph-timeout-01"
            }
        }

        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(content="帮我查一下其他订单")
                ]
            },
            config,
        )

        self.assertEqual(
            result["intent_result"]["reason"],
            "intent_recognition_failed",
        )

        replies = [
            message
            for message in result["messages"]
            if message.type == "ai"
        ]

        self.assertEqual(len(replies), 1)
        self.assertIn("稍后重试", replies[0].content)

        self.assertIsNone(result.get("pending_workflow"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

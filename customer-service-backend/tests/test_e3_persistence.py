"""E3-08：SQLite 会话持久化与隔离测试。"""

import unittest
from uuid import uuid4
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from my_agent.graph import graph
from my_agent.intent import IntentResult, SubIntent
from my_agent.checkpoint import DB_PATH


class TestPersistence(unittest.TestCase):

    @patch("my_agent.nodes.recognize_intent")
    def test_thread_isolation(self, mock_intent):
        # 两个独立会话
        config_a = {
            "configurable": {
                "thread_id": f"e3-user-a-{uuid4().hex}"
            }
        }

        config_b = {
            "configurable": {
                "thread_id": f"e3-user-b-{uuid4().hex}"
            }
        }

        mock_intent.return_value = IntentResult(
            intent="multi_intent",
            order_id="A20260410001",
            reason="会话隔离测试",
            sub_intents=[
                SubIntent(
                    intent="order_status",
                    order_id="A20260410001",
                ),
                SubIntent(
                    intent="shipping_reminder",
                    order_id="A20260410001",
                    condition="订单未发货",
                ),
            ],
        )

        # A 创建待办工作流
        result_a = graph.invoke(
            {
                "messages": [
                    HumanMessage(
                        content="查询订单 A20260410001，如果没发货就催一下"
                    )
                ]
            },
            config_a,
        )

        self.assertIsNotNone(result_a["pending_workflow"])

        # B 未参与任何对话
        snapshot_b = graph.get_state(config_b)

        self.assertFalse(snapshot_b.values)
        self.assertIsNone(
            snapshot_b.values.get("pending_workflow")
        )

        # A 的状态仍然完整
        snapshot_a = graph.get_state(config_a)

        self.assertEqual(
            snapshot_a.values["pending_workflow"],
            result_a["pending_workflow"],
        )

        mock_intent.assert_called_once()

    def test_sqlite_database_exists(self):
        self.assertTrue(
            DB_PATH.is_file(),
            f"SQLite 文件不存在: {DB_PATH}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

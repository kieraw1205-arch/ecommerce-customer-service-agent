"""LangGraph 对话状态存储配置。"""

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("AGENT_CHECKPOINT_PATH", str(PROJECT_ROOT / "data" / "checkpoints.sqlite")))


def make_checkpointer():
    """创建 LangGraph Checkpointer。"""

    backend = os.getenv("AGENT_CHECKPOINT_BACKEND", "sqlite")

    if backend == "memory":
        return MemorySaver()

    if backend != "sqlite":
        raise ValueError(f"不支持的 Checkpointer: {backend}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,
    )

    return SqliteSaver(connection)

"""跨进程、跨重启的客户状态持久化（SQLite 单文件）。

镜像 security/rate_limiter.py 的 SQLiteRateLimiter 范式：
- stdlib sqlite3，单共享连接（isolation_level=None，自动提交）
- threading.RLock 串行化所有操作
- 显式 BEGIN IMMEDIATE / COMMIT / ROLLBACK 保证多语句原子性
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import List, Optional

from core.customer_state import (
    CustomerState, state_to_dict, state_from_dict
)


class SQLiteStateStore:
    """客户状态的 SQLite 持久化后端。"""

    def __init__(self, db_path: str):
        self._lock = threading.RLock()

        # 目录不存在则自动创建（镜像 rate_limiter.py）
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._connection = sqlite3.connect(
            db_path,
            timeout=5,
            isolation_level=None,
            check_same_thread=False
        )
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_state (
                customer_id            TEXT PRIMARY KEY,
                is_escalated           INTEGER NOT NULL DEFAULT 0,
                is_not_interested      INTEGER NOT NULL DEFAULT 0,
                consecutive_issues     INTEGER NOT NULL DEFAULT 0,
                message_history_json   TEXT NOT NULL DEFAULT '[]',
                action_timestamps_json TEXT NOT NULL DEFAULT '[]',
                updated_at             TEXT NOT NULL
            )
            """
        )

    def load(self, customer_id: str) -> Optional[CustomerState]:
        """载入单个客户状态；不存在返回 None。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT is_escalated, is_not_interested, consecutive_issues, "
                "message_history_json, action_timestamps_json "
                "FROM customer_state WHERE customer_id = ?",
                (customer_id,)
            ).fetchone()
            if row is None:
                return None
            return state_from_dict({
                "customer_id": customer_id,
                "is_escalated": bool(row[0]),
                "is_not_interested": bool(row[1]),
                "consecutive_issues": int(row[2]),
                "message_history": json.loads(row[3]),
                "action_timestamps": json.loads(row[4]),
            })

    def save(self, state: CustomerState) -> None:
        """全行 upsert 保存客户状态。"""
        data = state_to_dict(state)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT INTO customer_state
                        (customer_id, is_escalated, is_not_interested,
                         consecutive_issues, message_history_json,
                         action_timestamps_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(customer_id) DO UPDATE SET
                        is_escalated = excluded.is_escalated,
                        is_not_interested = excluded.is_not_interested,
                        consecutive_issues = excluded.consecutive_issues,
                        message_history_json = excluded.message_history_json,
                        action_timestamps_json = excluded.action_timestamps_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        data["customer_id"],
                        int(data["is_escalated"]),
                        int(data["is_not_interested"]),
                        int(data["consecutive_issues"]),
                        json.dumps(data["message_history"]),
                        json.dumps(data["action_timestamps"]),
                        datetime.now().isoformat(),
                    )
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def delete(self, customer_id: str) -> None:
        """删除单个客户状态。"""
        with self._lock:
            self._connection.execute(
                "DELETE FROM customer_state WHERE customer_id = ?", (customer_id,)
            )

    def list_all(self) -> List[CustomerState]:
        """列出所有客户状态（从 DB 重建，非内存缓存对象）。"""
        with self._lock:
            rows = self._connection.execute(
                "SELECT customer_id FROM customer_state ORDER BY customer_id"
            ).fetchall()
            return [self.load(row[0]) for row in rows]

    def close(self) -> None:
        """关闭数据库连接，便于优雅退出和测试清理临时文件。"""
        with self._lock:
            self._connection.close()

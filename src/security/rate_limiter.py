"""线程安全、可选持久化的滑动窗口限流器。"""

from collections import deque
import os
import sqlite3
import threading
import time
from typing import Deque, Optional


class RateLimitError(Exception):
    """速率限制异常"""
    pass


class SlidingWindowRateLimiter:
    """单进程内使用的线程安全滑动窗口限流器。"""

    def __init__(self, window_seconds: int = 60, max_messages: int = 1):
        self.window_seconds = window_seconds
        self.max_messages = max_messages
        self._timestamps: Deque[float] = deque()
        self._lock = threading.RLock()

    def _clean_expired_timestamps(self, current_time: float) -> None:
        cutoff_time = current_time - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff_time:
            self._timestamps.popleft()

    def can_send_message(self, current_time: Optional[float] = None) -> bool:
        """只读检查；真正发送必须使用 reserve_message。"""
        if current_time is None:
            current_time = time.time()
        with self._lock:
            self._clean_expired_timestamps(current_time)
            return len(self._timestamps) < self.max_messages

    def reserve_message(self, current_time: Optional[float] = None) -> bool:
        """原子地检查并预留一次发送额度，避免 check-then-act 竞态。"""
        if current_time is None:
            current_time = time.time()
        with self._lock:
            self._clean_expired_timestamps(current_time)
            if len(self._timestamps) >= self.max_messages:
                return False
            self._timestamps.append(current_time)
            return True

    def record_message(self, current_time: Optional[float] = None) -> None:
        """兼容旧接口；记录前仍会原子检查限流。"""
        if not self.reserve_message(current_time):
            raise RateLimitError(
                f"Rate limit exceeded: max {self.max_messages} messages "
                f"per {self.window_seconds} seconds"
            )

    def get_wait_time(self, current_time: Optional[float] = None) -> float:
        if current_time is None:
            current_time = time.time()
        with self._lock:
            self._clean_expired_timestamps(current_time)
            if len(self._timestamps) < self.max_messages:
                return 0.0
            return max(0.0, self._timestamps[0] + self.window_seconds - current_time)

    def reset(self) -> None:
        with self._lock:
            self._timestamps.clear()

    def get_timestamps(self) -> list[float]:
        with self._lock:
            return list(self._timestamps)


class SQLiteRateLimiter:
    """使用 SQLite 原子事务实现跨进程、跨重启的限流记录。"""

    def __init__(self, db_path: str, window_seconds: int = 60, max_messages: int = 1):
        self.window_seconds = window_seconds
        self.max_messages = max_messages
        self._lock = threading.RLock()

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
            CREATE TABLE IF NOT EXISTS outbound_message_timestamps (
                customer_id TEXT NOT NULL,
                sent_at REAL NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_outbound_customer_time
            ON outbound_message_timestamps(customer_id, sent_at)
            """
        )

    def _clean_expired(self, customer_id: str, current_time: float) -> None:
        cutoff_time = current_time - self.window_seconds
        self._connection.execute(
            "DELETE FROM outbound_message_timestamps "
            "WHERE customer_id = ? AND sent_at < ?",
            (customer_id, cutoff_time)
        )

    def can_send_message(self, customer_id: str, current_time: Optional[float] = None) -> bool:
        if current_time is None:
            current_time = time.time()
        with self._lock:
            self._clean_expired(customer_id, current_time)
            row = self._connection.execute(
                "SELECT COUNT(*) FROM outbound_message_timestamps WHERE customer_id = ?",
                (customer_id,)
            ).fetchone()
            return int(row[0]) < self.max_messages

    def reserve_message(self, customer_id: str, current_time: Optional[float] = None) -> bool:
        """在 BEGIN IMMEDIATE 事务中完成清理、检查和写入。"""
        if current_time is None:
            current_time = time.time()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._clean_expired(customer_id, current_time)
                row = self._connection.execute(
                    "SELECT COUNT(*) FROM outbound_message_timestamps WHERE customer_id = ?",
                    (customer_id,)
                ).fetchone()
                if int(row[0]) >= self.max_messages:
                    self._connection.execute("ROLLBACK")
                    return False

                self._connection.execute(
                    "INSERT INTO outbound_message_timestamps(customer_id, sent_at) VALUES (?, ?)",
                    (customer_id, current_time)
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def record_message(self, customer_id: str, current_time: Optional[float] = None) -> None:
        if not self.reserve_message(customer_id, current_time):
            raise RateLimitError(
                f"Rate limit exceeded: max {self.max_messages} messages "
                f"per {self.window_seconds} seconds"
            )

    def get_wait_time(self, customer_id: str, current_time: Optional[float] = None) -> float:
        if current_time is None:
            current_time = time.time()
        with self._lock:
            self._clean_expired(customer_id, current_time)
            row = self._connection.execute(
                "SELECT MIN(sent_at), COUNT(*) FROM outbound_message_timestamps "
                "WHERE customer_id = ?",
                (customer_id,)
            ).fetchone()
            if not row or int(row[1]) < self.max_messages:
                return 0.0
            return max(0.0, float(row[0]) + self.window_seconds - current_time)

    def reset(self, customer_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM outbound_message_timestamps WHERE customer_id = ?",
                (customer_id,)
            )

    def reset_all(self) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM outbound_message_timestamps")

    def get_timestamps(self, customer_id: str) -> list[float]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT sent_at FROM outbound_message_timestamps "
                "WHERE customer_id = ? ORDER BY sent_at",
                (customer_id,)
            ).fetchall()
            return [float(row[0]) for row in rows]

    def close(self) -> None:
        """关闭数据库连接，便于服务优雅退出和测试清理临时文件。"""
        with self._lock:
            self._connection.close()


class PerCustomerRateLimiter:
    """按客户限流；未配置数据库时使用线程安全内存后端。"""

    def __init__(
        self,
        window_seconds: int = 60,
        max_messages: int = 1,
        storage_path: Optional[str] = None
    ):
        self.window_seconds = window_seconds
        self.max_messages = max_messages
        self._lock = threading.RLock()
        self._persistent = SQLiteRateLimiter(
            storage_path, window_seconds, max_messages
        ) if storage_path else None
        self._limiters: dict[str, SlidingWindowRateLimiter] = {}

    def _get_limiter(self, customer_id: str) -> SlidingWindowRateLimiter:
        with self._lock:
            if customer_id not in self._limiters:
                self._limiters[customer_id] = SlidingWindowRateLimiter(
                    window_seconds=self.window_seconds,
                    max_messages=self.max_messages
                )
            return self._limiters[customer_id]

    def can_send_message(self, customer_id: str, current_time: Optional[float] = None) -> bool:
        if self._persistent:
            return self._persistent.can_send_message(customer_id, current_time)
        return self._get_limiter(customer_id).can_send_message(current_time)

    def reserve_message(self, customer_id: str, current_time: Optional[float] = None) -> bool:
        if self._persistent:
            return self._persistent.reserve_message(customer_id, current_time)
        return self._get_limiter(customer_id).reserve_message(current_time)

    def record_message(self, customer_id: str, current_time: Optional[float] = None) -> None:
        if not self.reserve_message(customer_id, current_time):
            raise RateLimitError(
                f"Rate limit exceeded: max {self.max_messages} messages "
                f"per {self.window_seconds} seconds"
            )

    def get_wait_time(self, customer_id: str, current_time: Optional[float] = None) -> float:
        if self._persistent:
            return self._persistent.get_wait_time(customer_id, current_time)
        return self._get_limiter(customer_id).get_wait_time(current_time)

    def reset(self, customer_id: str) -> None:
        if self._persistent:
            self._persistent.reset(customer_id)
        elif customer_id in self._limiters:
            self._limiters[customer_id].reset()

    def reset_all(self) -> None:
        if self._persistent:
            self._persistent.reset_all()
        else:
            with self._lock:
                for limiter in self._limiters.values():
                    limiter.reset()

    def get_timestamps(self, customer_id: str) -> list[float]:
        if self._persistent:
            return self._persistent.get_timestamps(customer_id)
        return self._get_limiter(customer_id).get_timestamps()

    def close(self) -> None:
        """关闭持久化后端；内存后端无需处理。"""
        if self._persistent:
            self._persistent.close()

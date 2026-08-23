"""
动作执行器模块

这是"单一动作网关"，所有动作必须通过这里执行。

实现的约束：
- 约束 1：速率限制检查（任意 60 秒窗口最多 1 条消息）
- 约束 3：动作白名单 + escalate 后静默检查（100% 代码强制）
"""

import time
from dataclasses import dataclass
from typing import Optional
from config import Config
from core.customer_state import CustomerState, Action
from security.input_validator import is_safe_reply_draft
from security.rate_limiter import PerCustomerRateLimiter


class SecurityError(Exception):
    """安全约束违反异常"""
    pass


class RateLimitError(Exception):
    """速率限制异常"""
    pass


class EscalatedStateError(Exception):
    """已 escalate 状态下的非法操作"""
    pass


class NotInterestedStateError(Exception):
    """已结束会话下的非法操作"""
    pass


@dataclass
class ExecutionResult:
    """动作执行结果"""
    action: str  # 执行的动作
    success: bool  # 是否成功
    message: Optional[str] = None  # 结果消息
    error: Optional[str] = None  # 错误信息


class ActionExecutor:
    """
    动作执行器 - 单一动作网关

    所有约束在这里强制执行：
    - 约束 1：速率限制
    - 约束 3：动作白名单 + escalate 静默
    """

    # 动作白名单（约束 3）
    ALLOWED_ACTIONS = {
        Action.REPLY.value,
        Action.SCHEDULE_FOLLOWUP.value,
        Action.ESCALATE_TO_HUMAN.value,
        Action.MARK_NOT_INTERESTED.value
    }

    def __init__(self):
        """初始化执行器"""
        # 速率限制器（约束 1）
        self.rate_limiter = PerCustomerRateLimiter(
            window_seconds=Config.RATE_LIMIT_WINDOW_SECONDS,
            max_messages=Config.RATE_LIMIT_MAX_MESSAGES,
            storage_path=Config.RATE_LIMIT_DB_PATH or None
        )

    def execute(
        self,
        action: str,
        state: CustomerState,
        reply_content: Optional[str] = None,
        current_time: Optional[float] = None
    ) -> ExecutionResult:
        """
        执行动作

        这是唯一的动作执行入口，所有约束在这里检查。

        Args:
            action: 要执行的动作
            state: 客户状态
            reply_content: 回复内容（action=reply 时需要）
            current_time: 当前时间戳（用于测试）

        Returns:
            ExecutionResult: 执行结果

        Raises:
            SecurityError: 违反安全约束（白名单、escalate 静默）
            RateLimitError: 违反速率限制
        """
        if current_time is None:
            current_time = time.time()

        # ==================== 约束检查（按顺序） ====================

        # 约束 3.1: 动作白名单检查
        # 这是第一道防线，任何不在白名单内的动作都被拒绝
        if action not in self.ALLOWED_ACTIONS:
            raise SecurityError(
                f"Unauthorized action: '{action}'. "
                f"Allowed actions: {self.ALLOWED_ACTIONS}"
            )

        # 约束 3.2: escalate 后静默检查
        # 一旦 escalate，除了 escalate 本身，不能执行任何其他动作
        if state.is_escalated and action != Action.ESCALATE_TO_HUMAN.value:
            raise EscalatedStateError(
                f"Cannot execute action '{action}' after escalation. "
                f"Customer {state.customer_id} is waiting for human agent."
            )

        # 终态检查：标记不感兴趣后，不允许继续自动处理会话
        if state.is_not_interested and action != Action.MARK_NOT_INTERESTED.value:
            raise NotInterestedStateError(
                f"Cannot execute action '{action}' after customer opted out."
            )

        # 回复安全检查：所有 reply 必须经过唯一动作网关
        if action == Action.REPLY.value and reply_content is not None:
            if not is_safe_reply_draft(reply_content):
                raise SecurityError("Unsafe reply content blocked")

        # 回复内容为空时不应消耗发送额度
        if action == Action.REPLY.value and not reply_content:
            return ExecutionResult(
                action=Action.REPLY.value,
                success=False,
                error="Reply content is required"
            )

        # 约束 1：原子预留发送额度，避免并发 check-then-act 竞态
        if action == Action.REPLY.value:
            if not self.rate_limiter.reserve_message(state.customer_id, current_time):
                wait_time = self.rate_limiter.get_wait_time(state.customer_id, current_time)
                raise RateLimitError(
                    f"Rate limit exceeded for customer {state.customer_id}. "
                    f"Please wait {wait_time:.1f} seconds before next message."
                )

        # ==================== 执行动作 ====================

        try:
            if action == Action.REPLY.value:
                return self._execute_reply(state, reply_content, current_time)

            elif action == Action.SCHEDULE_FOLLOWUP.value:
                return self._execute_schedule_followup(state)

            elif action == Action.ESCALATE_TO_HUMAN.value:
                return self._execute_escalate(state)

            elif action == Action.MARK_NOT_INTERESTED.value:
                return self._execute_mark_not_interested(state)

            else:
                # 理论上不会到这里（白名单已检查），但保持防御性
                raise SecurityError(f"Unknown action: {action}")

        except Exception as e:
            # 执行失败，返回错误结果
            return ExecutionResult(
                action=action,
                success=False,
                error=str(e)
            )

    def _execute_reply(
        self,
        state: CustomerState,
        reply_content: Optional[str],
        current_time: float
    ) -> ExecutionResult:
        """
        执行 reply 动作

        Args:
            state: 客户状态
            reply_content: 回复内容
            current_time: 当前时间戳

        Returns:
            ExecutionResult: 执行结果
        """
        if not reply_content:
            return ExecutionResult(
                action=Action.REPLY.value,
                success=False,
                error="Reply content is required"
            )

        # 添加消息到历史
        state.add_message(role="agent", content=reply_content)

        return ExecutionResult(
            action=Action.REPLY.value,
            success=True,
            message=reply_content
        )

    def _execute_schedule_followup(self, state: CustomerState) -> ExecutionResult:
        """
        执行 schedule_followup 动作

        标记为稍后跟进，本轮不回复

        Args:
            state: 客户状态

        Returns:
            ExecutionResult: 执行结果
        """
        return ExecutionResult(
            action=Action.SCHEDULE_FOLLOWUP.value,
            success=True,
            message="Marked for follow-up"
        )

    def _execute_escalate(self, state: CustomerState) -> ExecutionResult:
        """
        执行 escalate_to_human 动作

        转人工后，设置 is_escalated 标志（约束 3）

        Args:
            state: 客户状态

        Returns:
            ExecutionResult: 执行结果
        """
        # 设置 escalate 标志（约束 3）
        state.escalate()

        return ExecutionResult(
            action=Action.ESCALATE_TO_HUMAN.value,
            success=True,
            message="Escalated to human agent"
        )

    def _execute_mark_not_interested(self, state: CustomerState) -> ExecutionResult:
        """
        执行 mark_not_interested 动作

        标记为不感兴趣，结束会话

        Args:
            state: 客户状态

        Returns:
            ExecutionResult: 执行结果
        """
        state.mark_not_interested()

        return ExecutionResult(
            action=Action.MARK_NOT_INTERESTED.value,
            success=True,
            message="Marked as not interested"
        )

    def can_execute(self, action: str, state: CustomerState) -> tuple[bool, Optional[str]]:
        """
        检查是否可以执行某个动作（不实际执行）

        用于预检查，返回是否可以执行和原因

        Args:
            action: 要检查的动作
            state: 客户状态

        Returns:
            tuple[bool, Optional[str]]: (是否可以执行, 原因)
        """
        # 检查 1: 白名单
        if action not in self.ALLOWED_ACTIONS:
            return False, f"Action '{action}' not in whitelist"

        # 检查 2: escalate 静默
        if state.is_escalated and action != Action.ESCALATE_TO_HUMAN.value:
            return False, "Cannot execute actions after escalation"

        if state.is_not_interested and action != Action.MARK_NOT_INTERESTED.value:
            return False, "Cannot execute actions after customer opted out"

        # 检查 3: 速率限制（仅 reply）
        if action == Action.REPLY.value:
            if not self.rate_limiter.can_send_message(state.customer_id):
                wait_time = self.rate_limiter.get_wait_time(state.customer_id)
                return False, f"Rate limit: wait {wait_time:.1f}s"

        return True, None

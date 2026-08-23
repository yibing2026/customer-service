"""
主控制器模块 - Agent Controller

整合所有模块，实现完整的消息处理流程和状态机逻辑。

架构：
用户输入
  ↓
输入验证层
  ↓
状态机层（检查 escalate、更新连续问题计数）
  ↓
LLM 分类层
  ↓
动作网关层（约束检查 + 执行）
  ↓
输出结果
"""

from dataclasses import dataclass
from typing import Optional
import secrets
import time
from config import Config
from core.customer_state import StateManager, CustomerState, Intent, EmotionLevel
from core.action_executor import (
    ActionExecutor, ExecutionResult,
    SecurityError, RateLimitError, EscalatedStateError,
    NotInterestedStateError
)
from security.input_validator import InputValidator

# LLM 分类器是可选的（如果没有安装 google-generativeai）
try:
    from core.intent_classifier import IntentClassifier, LLM_AVAILABLE
    LLM_CLASSIFIER_AVAILABLE = LLM_AVAILABLE
except ImportError:
    LLM_CLASSIFIER_AVAILABLE = False
    IntentClassifier = None


@dataclass
class AgentResponse:
    """Agent 响应"""
    customer_id: str
    action: str  # 执行的动作
    message: Optional[str] = None  # 给用户的消息
    is_escalated: bool = False  # 是否已转人工
    is_not_interested: bool = False  # 是否已结束会话
    consecutive_issues: int = 0  # 连续问题计数
    debug_info: Optional[dict] = None  # 调试信息（可选）


class AgentController:
    """
    主控制器 - 整合所有模块

    约束实现：
    - 约束 1：速率限制（通过 ActionExecutor）
    - 约束 2：连续问题强制 escalate（状态机逻辑）
    - 约束 3：动作白名单 + escalate 静默（通过 ActionExecutor）
    - 约束 4：防止信息泄露（通过 InputValidator + IntentClassifier）
    """

    def __init__(self, use_llm: bool = True, state_storage_path: Optional[str] = None):
        """
        初始化控制器

        Args:
            use_llm: 是否使用 LLM 分类器（False 时使用规则分类）
            state_storage_path: 客户状态持久化 SQLite 路径；None 时回退到
                Config.CUSTOMER_STATE_DB_PATH，仍为空则使用内存后端
        """
        resolved_state_path = (
            state_storage_path
            if state_storage_path is not None
            else (Config.CUSTOMER_STATE_DB_PATH or None)
        )
        self.state_manager = StateManager(storage_path=resolved_state_path)
        self.input_validator = InputValidator()
        self.action_executor = ActionExecutor()

        # LLM 是默认正式模式；只有显式 use_llm=False 才允许离线规则模式
        self.use_llm = use_llm
        self._llm_mode_requested = use_llm
        self.degraded_mode = False
        self.degraded_reason: Optional[str] = None
        if self.use_llm:
            if not LLM_CLASSIFIER_AVAILABLE:
                self._enter_degraded_mode("llm_dependency_unavailable")
            else:
                try:
                    self.intent_classifier = IntentClassifier()
                except Exception:
                    self._enter_degraded_mode("llm_initialization_failed")
        else:
            self.intent_classifier = None

    def handle_message(
        self,
        customer_id: str,
        message: str,
        current_time: Optional[float] = None
    ) -> AgentResponse:
        """
        处理客户消息（主入口）

        这是完整的状态机流程，整合所有约束检查。

        Args:
            customer_id: 客户 ID
            message: 客户消息
            current_time: 当前时间戳（用于测试）

        Returns:
            AgentResponse: 处理结果
        """
        debug_info = {}

        # ==================== 步骤 1: 加载客户状态 ====================
        state = self.state_manager.get_or_create(customer_id)

        # ==================== 步骤 2: 检查 escalate 状态（约束 3） ====================
        # 已转人工时必须立即静默，不能被输入校验错误打断
        if state.is_escalated:
            return AgentResponse(
                customer_id=customer_id,
                action="silence",
                message="Waiting for human agent to respond",
                is_escalated=True,
                consecutive_issues=state.consecutive_issues
            )

        # ==================== 步骤 3: 输入验证（约束 4 第一层） ====================
        validation_result = self.input_validator.validate(message)

        if not validation_result.is_valid:
            # 输入验证失败，拒绝处理
            return AgentResponse(
                customer_id=customer_id,
                action="rejected",
                message=f"Input validation failed: {validation_result.error_message}",
                is_escalated=state.is_escalated,
                consecutive_issues=state.consecutive_issues
            )

        # 记录可疑输入（约束 4 防御）
        if validation_result.is_suspicious:
            debug_info["suspicious_input"] = True
            debug_info["validation_warnings"] = validation_result.warnings

        if state.is_not_interested:
            # 已结束会话，保持静默
            return AgentResponse(
                customer_id=customer_id,
                action="silence",
                message="Conversation ended because the customer is not interested",
                is_not_interested=True,
                consecutive_issues=state.consecutive_issues
            )

        # ==================== 步骤 4: LLM 意图分类 ====================
        if self.degraded_mode:
            return self._handle_degraded_mode(state, message, debug_info)
        elif self.use_llm:
            try:
                classification = self._classify_with_retry(
                    message,
                    history=[
                        {"role": msg.role, "content": msg.content}
                        for msg in state.message_history[-3:]  # 最近 3 条
                    ]
                )
            except Exception:
                self._enter_degraded_mode("llm_runtime_failure")
                return self._handle_degraded_mode(state, message, debug_info)

            intent = classification.intent
            emotion = classification.emotion
            suggested_action = classification.suggested_action
            reply_draft = classification.reply_draft
            debug_info["llm_classification"] = {
                "intent": intent,
                "emotion": emotion.value,
                "suggested_action": suggested_action,
                "language": classification.language
            }
        else:
            # 仅用于显式离线测试模式
            classification = self._rule_based_classification(message)
            intent = classification["intent"]
            emotion = classification["emotion"]
            suggested_action = classification["suggested_action"]
            reply_draft = classification.get("reply_draft")
            debug_info["rule_based_classification"] = {
                "intent": intent,
                "emotion": emotion.value,
                "suggested_action": suggested_action
            }

        # 添加客户消息到历史
        state.add_message(
            role="customer",
            content=message,
            intent=Intent(intent) if intent in [e.value for e in Intent] else Intent.OTHER,
            emotion=emotion
        )

        # ==================== 步骤 5: 状态机 - 更新连续问题计数（约束 2） ====================
        # 情绪分级：CALM 清零；MILD/UPSET/FURIOUS 都计入问题计数。
        # MILD 不会立即转人工（靠 LLM 建议 reply），累计到阈值仍会强制转人工。
        if intent == "off_topic" or emotion.counts_as_issue():
            # 答非所问或情绪不满，计数 +1
            state.increment_consecutive_issues()
            debug_info["consecutive_issues_incremented"] = True
        else:
            # 正常消息，计数清零
            state.reset_consecutive_issues()
            debug_info["consecutive_issues_reset"] = True

        # ==================== 步骤 6: 强制 escalate 检查（约束 2） ====================
        if state.should_force_escalate():
            # 连续问题达到阈值，强制 escalate
            suggested_action = "escalate_to_human"
            reply_draft = None
            debug_info["forced_escalate"] = True
            debug_info["reason"] = f"Consecutive issues >= {Config.MAX_CONSECUTIVE_ISSUES}"

        # ==================== 步骤 7: 执行动作（约束 1, 3） ====================
        try:
            execution_result = self.action_executor.execute(
                action=suggested_action,
                state=state,
                reply_content=reply_draft,
                current_time=current_time
            )

            # 保存状态
            self.state_manager.save(state)

            # 构建响应
            return AgentResponse(
                customer_id=customer_id,
                action=execution_result.action,
                message=execution_result.message if execution_result.success else execution_result.error,
                is_escalated=state.is_escalated,
                is_not_interested=state.is_not_interested,
                consecutive_issues=state.consecutive_issues,
                debug_info=debug_info
            )

        except RateLimitError as e:
            # 速率限制异常；客户消息与计数已更新，需落盘
            self.state_manager.save(state)
            return AgentResponse(
                customer_id=customer_id,
                action="rate_limited",
                message=str(e),
                is_escalated=state.is_escalated,
                consecutive_issues=state.consecutive_issues,
                debug_info=debug_info
            )

        except (SecurityError, EscalatedStateError, NotInterestedStateError) as e:
            # 安全约束违反；客户消息与计数已更新，需落盘
            self.state_manager.save(state)
            return AgentResponse(
                customer_id=customer_id,
                action="security_violation",
                message=str(e),
                is_escalated=state.is_escalated,
                consecutive_issues=state.consecutive_issues,
                debug_info=debug_info
            )

        except Exception as e:
            # 其他异常；客户消息与计数已更新，需落盘
            self.state_manager.save(state)
            return AgentResponse(
                customer_id=customer_id,
                action="error",
                message=f"Error: {str(e)}",
                is_escalated=state.is_escalated,
                consecutive_issues=state.consecutive_issues,
                debug_info=debug_info
            )

    def _enter_degraded_mode(self, reason: str) -> None:
        """打开 LLM 熔断，后续请求只执行安全降级动作。"""
        self.use_llm = False
        self.intent_classifier = None
        self.degraded_mode = True
        self.degraded_reason = reason

    def reactivate_llm(self) -> bool:
        """供已认证人工/运维层调用：探测成功后解除 LLM 熔断。"""
        if not self._llm_mode_requested or not LLM_CLASSIFIER_AVAILABLE:
            return False

        previous_classifier = self.intent_classifier
        try:
            candidate = IntentClassifier()
            self.intent_classifier = candidate
            self._classify_with_retry(
                "Health check: classify this neutral customer message.",
                history=[]
            )
        except Exception:
            self.intent_classifier = previous_classifier
            self._enter_degraded_mode("llm_reactivation_probe_failed")
            return False

        self.use_llm = True
        self.degraded_mode = False
        self.degraded_reason = None
        return True

    def _classify_with_retry(self, message: str, history: list[dict]):
        """有限重试 LLM；耗尽后抛错，由控制器进入降级模式。"""
        last_error = None
        attempts = Config.LLM_MAX_RETRIES + 1

        for attempt in range(attempts):
            try:
                return self.intent_classifier.classify(message, history=history)
            except Exception as error:
                last_error = error
                if attempt < attempts - 1:
                    time.sleep(Config.LLM_RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise RuntimeError("LLM classification retries exhausted") from last_error

    def _handle_degraded_mode(
        self,
        state: CustomerState,
        message: str,
        debug_info: dict
    ) -> AgentResponse:
        """LLM 不可用时不猜测意图，只安排后续处理，不自动回复。"""
        state.add_message(role="customer", content=message)
        debug_info["degraded_mode"] = True
        debug_info["degraded_reason"] = self.degraded_reason

        execution_result = self.action_executor.execute(
            action="schedule_followup",
            state=state
        )
        self.state_manager.save(state)

        return AgentResponse(
            customer_id=state.customer_id,
            action=execution_result.action,
            message=execution_result.message if execution_result.success else execution_result.error,
            is_escalated=state.is_escalated,
            is_not_interested=state.is_not_interested,
            consecutive_issues=state.consecutive_issues,
            debug_info=debug_info
        )

    def _rule_based_classification(self, message: str) -> dict:
        """
        基于规则的意图分类（显式离线测试模式）

        只有调用方明确关闭 LLM 时使用；LLM 故障不会自动进入此路径。

        Args:
            message: 客户消息

        Returns:
            dict: 分类结果
        """
        message_lower = message.lower()

        # 优先级 1: 检查情绪不满（明显愤怒 → upset，建议转人工）
        if any(word in message_lower for word in ["angry", "terrible", "bad", "worst", "生气", "糟糕", "frustrated", "disappointed", "very angry"]):
            return {
                "intent": "other",
                "emotion": EmotionLevel.UPSET,
                "suggested_action": "escalate_to_human"
            }

        # 优先级 2: 检查答非所问（天气、哲学等）
        if any(word in message_lower for word in ["weather", "philosophy", "universe", "天气", "哲学", "宇宙", "ends"]):
            return {
                "intent": "off_topic",
                "emotion": EmotionLevel.CALM,
                "suggested_action": "schedule_followup"
            }

        # 优先级 3: 检查明确拒绝
        if any(word in message_lower for word in ["no", "not interested", "don't", "不感兴趣", "不需要"]):
            return {
                "intent": "reject",
                "emotion": EmotionLevel.CALM,
                "suggested_action": "mark_not_interested"
            }

        # 优先级 4: 检查感兴趣
        if any(word in message_lower for word in ["interested", "want", "need", "like", "感兴趣", "想要"]):
            return {
                "intent": "interested",
                "emotion": EmotionLevel.CALM,
                "suggested_action": "reply",
                "reply_draft": "Thank you for your interest! How can I help you?"
            }

        # 默认：需要更多信息
        return {
            "intent": "need_info",
            "emotion": EmotionLevel.CALM,
            "suggested_action": "reply",
            "reply_draft": "I'd be happy to help. Could you tell me more about what you're looking for?"
        }

    def get_customer_state(self, customer_id: str) -> Optional[CustomerState]:
        """获取客户状态"""
        return self.state_manager.get(customer_id)

    def human_reactivate(self, customer_id: str, operator_token: str) -> bool:
        """人工/运维恢复客户会话；不会清除历史或重置限流记录。"""
        configured_token = Config.HUMAN_OPERATOR_TOKEN
        if not configured_token or not secrets.compare_digest(
            operator_token or "", configured_token
        ):
            raise PermissionError("Invalid human operator credentials")

        state = self.state_manager.get(customer_id)
        if state is None or not state.is_escalated:
            return False

        state.reactivate_by_human()
        self.state_manager.save(state)
        return True

    def reset_customer_for_test(self, customer_id: str) -> None:
        """仅供测试清理状态；不作为客户或人工恢复接口。"""
        self.state_manager.delete(customer_id)
        self.action_executor.rate_limiter.reset(customer_id)

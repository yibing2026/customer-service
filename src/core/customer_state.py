"""
客户状态管理模块

实现约束：
- 约束 2：维护 consecutive_issues 计数器，达到 2 时触发 escalate
- 约束 3：维护 is_escalated 标志，escalate 后拒绝所有自动动作
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class Intent(Enum):
    """客户意图枚举"""
    INTERESTED = "interested"      # 有兴趣
    NEED_INFO = "need_info"        # 需要更多信息
    REJECT = "reject"              # 明确拒绝
    OFF_TOPIC = "off_topic"        # 答非所问
    OTHER = "other"                # 其他


class EmotionLevel(Enum):
    """
    客户情绪强度枚举（分级，替代布尔 is_upset）

    强度递增：CALM < MILD < UPSET < FURIOUS
    - CALM：平静，无负面情绪
    - MILD：轻微不满，仍可继续沟通
    - UPSET：明显不满/愤怒，建议转人工
    - FURIOUS：极度愤怒/辱骂，立即转人工
    """
    CALM = "calm"          # 平静
    MILD = "mild"          # 轻微不满
    UPSET = "upset"        # 明显不满/愤怒
    FURIOUS = "furious"    # 极度愤怒

    def counts_as_issue(self) -> bool:
        """
        是否计入连续问题计数（约束 2）

        除了 CALM 之外都算问题信号：MILD 也会让计数器 +1，
        但不会立即转人工（转人工靠累计阈值强制触发）。

        Returns:
            bool: True 表示该情绪应计入连续问题计数
        """
        return self is not EmotionLevel.CALM

    def is_upset(self) -> bool:
        """
        是否达到需要立即转人工的情绪强度

        保留布尔语义的便捷方法：UPSET 及以上返回 True。

        Returns:
            bool: True 表示明显不满（upset 或 furious）
        """
        return self in (EmotionLevel.UPSET, EmotionLevel.FURIOUS)


class Action(Enum):
    """动作枚举"""
    REPLY = "reply"                          # 回复
    SCHEDULE_FOLLOWUP = "schedule_followup"  # 安排后续跟进
    ESCALATE_TO_HUMAN = "escalate_to_human"  # 转人工
    MARK_NOT_INTERESTED = "mark_not_interested"  # 标记不感兴趣


@dataclass
class Message:
    """消息记录"""
    role: str  # "customer" 或 "agent"
    content: str
    timestamp: datetime
    intent: Optional[Intent] = None  # 仅客户消息有意图分类
    emotion: Optional[EmotionLevel] = None  # 仅客户消息有情绪分级


@dataclass
class CustomerState:
    """
    客户状态数据结构

    约束实现：
    - consecutive_issues: 连续答非所问/情绪不满的计数（约束 2）
    - is_escalated: 是否已转人工，转人工后此标志为 True（约束 3）
    - action_timestamps: 动作时间戳列表，用于速率限制（约束 1）
    """
    customer_id: str
    is_escalated: bool = False
    is_not_interested: bool = False
    consecutive_issues: int = 0
    message_history: List[Message] = field(default_factory=list)
    action_timestamps: List[float] = field(default_factory=list)  # Unix 时间戳

    def add_message(self, role: str, content: str,
                   intent: Optional[Intent] = None,
                   emotion: Optional[EmotionLevel] = None) -> None:
        """添加消息到历史记录"""
        message = Message(
            role=role,
            content=content,
            timestamp=datetime.now(),
            intent=intent,
            emotion=emotion
        )
        self.message_history.append(message)

    def add_action_timestamp(self, timestamp: float) -> None:
        """添加动作时间戳（用于速率限制）"""
        self.action_timestamps.append(timestamp)

    def increment_consecutive_issues(self) -> None:
        """
        增加连续问题计数
        约束 2：当客户消息被判定为 off_topic 或情绪非 calm（mild/upset/furious）时调用
        """
        self.consecutive_issues += 1

    def reset_consecutive_issues(self) -> None:
        """
        重置连续问题计数
        约束 2：当客户消息正常（非 off_topic 且不 upset）时调用
        """
        self.consecutive_issues = 0

    def escalate(self) -> None:
        """
        标记为已转人工
        约束 3：此后必须拒绝所有自动动作
        """
        self.is_escalated = True

    def reactivate_by_human(self) -> None:
        """由人工恢复自动处理，并清除本轮连续异常计数。"""
        self.is_escalated = False
        self.reset_consecutive_issues()

    def mark_not_interested(self) -> None:
        """标记客户不感兴趣并结束会话。"""
        self.is_not_interested = True

    def should_force_escalate(self) -> bool:
        """
        判断是否应该强制转人工
        约束 2：连续问题计数 >= 2 时返回 True
        """
        return self.consecutive_issues >= 2


def _serialize_message(msg: Message) -> dict:
    """序列化单条消息为字典（datetime 用 ISO 8601，枚举用 .value）。"""
    return {
        "role": msg.role,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat(),
        "intent": msg.intent.value if msg.intent is not None else None,
        "emotion": msg.emotion.value if msg.emotion is not None else None,
    }


def _parse_intent(value: Optional[str]) -> Optional[Intent]:
    """解析意图枚举，未知值保守回退为 OTHER。"""
    if value is None:
        return None
    try:
        return Intent(value)
    except ValueError:
        return Intent.OTHER


def _parse_emotion(value: Optional[str]) -> Optional[EmotionLevel]:
    """解析情绪分级枚举，未知值保守回退为 CALM。"""
    if value is None:
        return None
    try:
        return EmotionLevel(value)
    except ValueError:
        return EmotionLevel.CALM


def _deserialize_message(data: dict) -> Message:
    """从字典反序列化消息。"""
    return Message(
        role=data["role"],
        content=data["content"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        intent=_parse_intent(data.get("intent")),
        emotion=_parse_emotion(data.get("emotion")),
    )


def state_to_dict(state: CustomerState) -> dict:
    """将客户状态完整序列化为 JSON 安全的字典（含消息历史全文）。"""
    return {
        "customer_id": state.customer_id,
        "is_escalated": state.is_escalated,
        "is_not_interested": state.is_not_interested,
        "consecutive_issues": state.consecutive_issues,
        "message_history": [_serialize_message(m) for m in state.message_history],
        "action_timestamps": list(state.action_timestamps),
    }


def state_from_dict(data: dict) -> CustomerState:
    """从字典重建客户状态（与 state_to_dict 互为逆操作）。"""
    return CustomerState(
        customer_id=data["customer_id"],
        is_escalated=bool(data.get("is_escalated", False)),
        is_not_interested=bool(data.get("is_not_interested", False)),
        consecutive_issues=int(data.get("consecutive_issues", 0)),
        message_history=[
            _deserialize_message(m) for m in data.get("message_history", [])
        ],
        action_timestamps=list(data.get("action_timestamps", [])),
    )


class StateManager:
    """
    客户状态管理器

    使用内存字典存储所有客户状态
    支持导出/导入 JSON 用于调试
    """

    def __init__(self, storage_path: Optional[str] = None):
        self._states: dict[str, CustomerState] = {}
        self._store: Optional["SQLiteStateStore"] = None
        if storage_path:
            # 延迟导入避免 customer_state <-> state_store 循环依赖
            from core.state_store import SQLiteStateStore
            self._store = SQLiteStateStore(storage_path)

    def get_or_create(self, customer_id: str) -> CustomerState:
        """获取或创建客户状态；持久化时先尝试从 store 载入。"""
        if customer_id in self._states:
            return self._states[customer_id]
        state = None
        if self._store is not None:
            state = self._store.load(customer_id)
        if state is None:
            state = CustomerState(customer_id=customer_id)
        self._states[customer_id] = state
        return state

    def get(self, customer_id: str) -> Optional[CustomerState]:
        """获取客户状态；先查内存缓存，再查持久化 store。"""
        if customer_id in self._states:
            return self._states[customer_id]
        if self._store is not None:
            state = self._store.load(customer_id)
            if state is not None:
                self._states[customer_id] = state
                return state
        return None

    def save(self, state: CustomerState) -> None:
        """保存客户状态到内存缓存，并在启用持久化时写入 store。"""
        self._states[state.customer_id] = state
        if self._store is not None:
            self._store.save(state)

    def delete(self, customer_id: str) -> None:
        """删除客户状态（内存缓存 + 持久化 store）。"""
        self._states.pop(customer_id, None)
        if self._store is not None:
            self._store.delete(customer_id)

    def list_all(self) -> List[CustomerState]:
        """列出所有客户状态；持久化时以 store 为唯一真源。"""
        if self._store is not None:
            return self._store.list_all()
        return list(self._states.values())

    def close(self) -> None:
        """关闭持久化后端连接（内存后端无需处理）。"""
        if self._store is not None:
            self._store.close()

    def to_dict(self) -> dict:
        """导出为字典（用于 JSON 序列化）"""
        return {
            customer_id: {
                "customer_id": state.customer_id,
                "is_escalated": state.is_escalated,
                "is_not_interested": state.is_not_interested,
                "consecutive_issues": state.consecutive_issues,
                "action_timestamps": state.action_timestamps,
                "message_count": len(state.message_history)
            }
            for customer_id, state in self._states.items()
        }

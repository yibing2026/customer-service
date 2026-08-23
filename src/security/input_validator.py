"""
输入验证模块

实现约束 4 的第一层防御：
- 输入长度限制
- 检测明显的提示词注入模式
- 记录可疑输入用于监控

注意：这只是第一道防线，不是唯一防御。
"""

import re
from dataclasses import dataclass
from typing import List, Optional
from config import Config


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool  # 是否通过验证
    error_message: Optional[str] = None  # 错误信息（验证失败时）
    warnings: List[str] = None  # 警告信息（可疑但未拒绝）
    is_suspicious: bool = False  # 是否检测到可疑模式

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


REPLY_SENSITIVE_KEYWORDS = (
    "system prompt",
    "instruction",
    "internal rule",
    "底线",
    "内部规则",
    "系统提示词",
)


def is_safe_reply_draft(reply_draft: Optional[str]) -> bool:
    """检查待发送回复是否包含明显的内部信息泄露内容。"""
    if reply_draft is None:
        return True
    if not isinstance(reply_draft, str):
        return False

    reply_lower = reply_draft.lower()
    return not any(
        keyword.lower() in reply_lower
        for keyword in REPLY_SENSITIVE_KEYWORDS
    )


class InputValidator:
    """
    输入验证器

    约束 4 第一层防御：
    - 检测明显的提示词注入尝试
    - 限制输入长度防止资源消耗
    - 记录可疑模式但不一定拒绝（避免误杀正常用户）
    """

    # 最大输入长度
    MAX_LENGTH = Config.MAX_INPUT_LENGTH

    # 可疑模式（提示词注入常见特征）
    SUSPICIOUS_PATTERNS = [
        # 直接命令模式
        r"(?i)(ignore|忽略|無視).{0,20}(previous|之前|earlier|先前|以前).{0,20}(instruction|指令|prompt|提示|rule|规则)",
        r"(?i)(forget|忘记|忘掉).{0,20}(previous|之前|earlier|先前|above|上面).{0,20}(instruction|指令|prompt|提示)",

        # 系统提示词套取
        r"(?i)(show|tell|reveal|给我|告诉我|显示|透露).{0,30}(system\s*prompt|系统提示词|system\s*instruction|系统指令)",
        r"(?i)(what|what's|whats).{0,20}(your|ur).{0,20}(system\s*prompt|prompt|instruction|rule)",

        # 角色重定义
        r"(?i)(you\s*are\s*now|现在你是|你现在是|from\s*now\s*on|从现在开始).{0,30}(assistant|助手|helper|bot|agent)",
        r"(?i)(act\s*as|扮演|充当|pretend).{0,20}(different|另一个|unrestricted|无限制|unfiltered)",

        # 规则探测
        r"(?i)(what|tell\s*me|说说).{0,20}(internal\s*rule|内部规则|price\s*rule|价格规则|bottom\s*line|底线)",
        r"(?i)(what.{0,10}s|how\s*much|多少钱|price|价格|cost|成本).{0,30}(real|actual|真实|internal|内部).{0,30}(rule|规则|price|价格)",

        # 直接执行命令
        r"(?i)(execute|执行|run|运行|eval|evaluate).{0,20}(action|动作|command|命令|function|函数)",
        r"(?i)(mark_not_interested|escalate|schedule_followup).{0,20}(directly|直接|without|不用|skip|跳过)",

        # DAN (Do Anything Now) 类提示
        r"(?i)(do\s*anything\s*now|DAN|developer\s*mode|开发者模式|越狱|jailbreak)",

        # 元指令注入
        r"(?i)(</system>|<\|im_end\|>|<\|endoftext\|>|###\s*Instruction|###\s*指令)",
    ]

    def __init__(self):
        """初始化验证器，编译正则表达式以提高性能"""
        self._compiled_patterns = [
            re.compile(pattern) for pattern in self.SUSPICIOUS_PATTERNS
        ]

    def validate(self, message: str) -> ValidationResult:
        """
        验证用户输入

        约束 4 实现：
        1. 长度检查（硬限制）
        2. 可疑模式检测（记录警告，可选择拒绝）

        Args:
            message: 用户输入的消息

        Returns:
            ValidationResult: 验证结果
        """
        warnings = []

        # 检查 1: 长度限制（硬限制）
        if len(message) > self.MAX_LENGTH:
            return ValidationResult(
                is_valid=False,
                error_message=f"Input too long: {len(message)} chars (max {self.MAX_LENGTH})"
            )

        # 检查 2: 空消息
        if not message or message.strip() == "":
            return ValidationResult(
                is_valid=False,
                error_message="Empty message"
            )

        # 检查 3: 可疑模式检测
        suspicious_matches = []
        for i, pattern in enumerate(self._compiled_patterns):
            match = pattern.search(message)
            if match:
                suspicious_matches.append({
                    "pattern_index": i,
                    "matched_text": match.group(0),
                    "position": match.span()
                })

        # 如果检测到可疑模式，记录警告
        is_suspicious = len(suspicious_matches) > 0
        if is_suspicious:
            warnings.append(
                f"Suspicious pattern detected: {len(suspicious_matches)} match(es)"
            )
            # 记录详细信息（用于日志）
            for match_info in suspicious_matches:
                warnings.append(
                    f"  Pattern #{match_info['pattern_index']}: "
                    f"'{match_info['matched_text']}' at {match_info['position']}"
                )

        # 策略选择：
        # 选项 A：检测到可疑模式就拒绝（严格模式，可能误杀）
        # 选项 B：只记录警告，不拒绝（宽松模式，记录后由后续层处理）
        #
        # 这里选择选项 B：记录但不拒绝
        # 理由：
        # 1. 避免误杀正常用户（例如用户真的在问"你的系统是怎么工作的"）
        # 2. 真正的防御在 LLM 层（prompt 设计 + function calling）
        # 3. 输入层的作用是"记录可疑行为"，用于监控和告警

        return ValidationResult(
            is_valid=True,  # 不拒绝，只记录
            warnings=warnings,
            is_suspicious=is_suspicious
        )

    def validate_strict(self, message: str) -> ValidationResult:
        """
        严格模式验证（检测到可疑模式就拒绝）

        可选的严格模式，用于高安全场景

        Args:
            message: 用户输入的消息

        Returns:
            ValidationResult: 验证结果
        """
        result = self.validate(message)

        # 如果检测到可疑模式，在严格模式下拒绝
        if result.is_suspicious:
            return ValidationResult(
                is_valid=False,
                error_message="Message rejected due to suspicious patterns",
                warnings=result.warnings,
                is_suspicious=True
            )

        return result

    def get_suspicious_snippet(self, message: str, max_length: int = 100) -> str:
        """
        获取消息的摘要（用于日志，避免记录完整消息）

        Args:
            message: 完整消息
            max_length: 最大长度

        Returns:
            str: 消息摘要
        """
        if len(message) <= max_length:
            return message

        return message[:max_length] + "..."

    @classmethod
    def add_custom_pattern(cls, pattern: str) -> None:
        """
        添加自定义可疑模式（用于扩展）

        Args:
            pattern: 正则表达式模式
        """
        cls.SUSPICIOUS_PATTERNS.append(pattern)

    def check_specific_keywords(self, message: str, keywords: List[str]) -> bool:
        """
        检查消息是否包含特定关键词（用于敏感信息过滤）

        Args:
            message: 消息内容
            keywords: 关键词列表

        Returns:
            bool: 是否包含任何关键词
        """
        message_lower = message.lower()
        for keyword in keywords:
            if keyword.lower() in message_lower:
                return True
        return False

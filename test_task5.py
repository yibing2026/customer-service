"""
任务 5 测试：动作执行器

测试内容：
1. 动作白名单验证（约束 3）
2. escalate 后静默检查（约束 3）
3. 速率限制集成（约束 1）
4. 各个动作的正确执行
5. 预检查功能
"""

import sys
import os
import time

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.insert(0, src_dir)

from core.action_executor import (
    ActionExecutor, ExecutionResult, SecurityError,
    RateLimitError, EscalatedStateError
)
from core.customer_state import CustomerState, Action


def test_action_whitelist():
    """测试 1: 动作白名单（约束 3）"""
    print("=" * 60)
    print("Test 1: Action Whitelist (Constraint 3)")
    print("=" * 60)

    executor = ActionExecutor()
    state = CustomerState(customer_id="test_001")

    # 合法动作应该通过白名单检查
    valid_actions = ["reply", "schedule_followup", "escalate_to_human", "mark_not_interested"]
    for action in valid_actions:
        can_exec, reason = executor.can_execute(action, state)
        # 注意：reply 可能因为其他原因（如速率限制）不能执行
        # 但应该通过白名单检查，所以这里只检查不是白名单问题
        if not can_exec and "not in whitelist" in reason:
            assert False, f"Valid action '{action}' rejected by whitelist"
        print(f"[OK] Action '{action}' passed whitelist check")

    # 非法动作应该被拒绝
    invalid_actions = ["delete_data", "send_spam", "hack_system", "evil_action"]
    for action in invalid_actions:
        try:
            executor.execute(action, state)
            assert False, f"Invalid action '{action}' should be rejected"
        except SecurityError as e:
            assert "Unauthorized action" in str(e)
            print(f"[OK] Invalid action '{action}' rejected: {str(e)[:60]}...")

    print()


def test_escalate_silence():
    """测试 2: escalate 后静默（约束 3）"""
    print("=" * 60)
    print("Test 2: Silence After Escalation (Constraint 3)")
    print("=" * 60)

    executor = ActionExecutor()
    state = CustomerState(customer_id="test_002")

    # 执行 escalate
    result = executor.execute(Action.ESCALATE_TO_HUMAN.value, state)
    assert result.success == True
    assert state.is_escalated == True
    print("[OK] Escalated to human successfully")

    # escalate 后，尝试执行其他动作应该被拒绝
    forbidden_actions = [
        Action.REPLY.value,
        Action.SCHEDULE_FOLLOWUP.value,
        Action.MARK_NOT_INTERESTED.value
    ]

    for action in forbidden_actions:
        try:
            executor.execute(action, state, reply_content="test")
            assert False, f"Action '{action}' should be blocked after escalation"
        except EscalatedStateError as e:
            assert "after escalation" in str(e)
            print(f"[OK] Action '{action}' blocked: {str(e)[:60]}...")

    # 但是可以再次 escalate（幂等性）
    result = executor.execute(Action.ESCALATE_TO_HUMAN.value, state)
    assert result.success == True
    print("[OK] Can escalate again (idempotent)")

    print()


def test_rate_limit_integration():
    """测试 3: 速率限制集成（约束 1）"""
    print("=" * 60)
    print("Test 3: Rate Limit Integration (Constraint 1)")
    print("=" * 60)

    executor = ActionExecutor()
    state = CustomerState(customer_id="test_003")

    t0 = 1000.0

    # 第一条消息应该成功
    result = executor.execute(
        Action.REPLY.value,
        state,
        reply_content="First message",
        current_time=t0
    )
    assert result.success == True
    print("[OK] First message sent successfully")

    # 立即发送第二条应该被速率限制拒绝
    try:
        executor.execute(
            Action.REPLY.value,
            state,
            reply_content="Second message",
            current_time=t0 + 1
        )
        assert False, "Second message should be rate limited"
    except RateLimitError as e:
        assert "Rate limit exceeded" in str(e)
        print(f"[OK] Second message blocked: {str(e)[:60]}...")

    # 60 秒后应该可以发送
    result = executor.execute(
        Action.REPLY.value,
        state,
        reply_content="Third message",
        current_time=t0 + 61
    )
    assert result.success == True
    print("[OK] Third message sent after 60s")

    # 非 reply 动作不受速率限制影响
    state2 = CustomerState(customer_id="test_004")
    executor.execute(Action.REPLY.value, state2, reply_content="msg", current_time=t0)

    # 立即执行 schedule_followup 应该成功
    result = executor.execute(Action.SCHEDULE_FOLLOWUP.value, state2, current_time=t0 + 1)
    assert result.success == True
    print("[OK] Non-reply actions not rate limited")

    print()


def test_reply_execution():
    """测试 4: reply 动作执行"""
    print("=" * 60)
    print("Test 4: Reply Action Execution")
    print("=" * 60)

    executor = ActionExecutor()
    state = CustomerState(customer_id="test_005")

    # 成功执行 reply
    reply_content = "Hello! Thank you for your interest."
    result = executor.execute(
        Action.REPLY.value,
        state,
        reply_content=reply_content
    )

    assert result.success == True
    assert result.action == Action.REPLY.value
    assert result.message == reply_content
    print(f"[OK] Reply executed: {reply_content[:40]}...")

    # 检查消息历史
    assert len(state.message_history) == 1
    assert state.message_history[0].role == "agent"
    assert state.message_history[0].content == reply_content
    print("[OK] Message added to history")

    # 没有 reply_content 应该失败
    state2 = CustomerState(customer_id="test_006")
    result = executor.execute(Action.REPLY.value, state2, reply_content=None)
    assert result.success == False
    assert "required" in result.error.lower()
    print("[OK] Reply without content fails")

    print()


def test_other_actions():
    """测试 5: 其他动作执行"""
    print("=" * 60)
    print("Test 5: Other Actions Execution")
    print("=" * 60)

    executor = ActionExecutor()

    # schedule_followup
    state1 = CustomerState(customer_id="test_007")
    result = executor.execute(Action.SCHEDULE_FOLLOWUP.value, state1)
    assert result.success == True
    assert result.action == Action.SCHEDULE_FOLLOWUP.value
    print("[OK] schedule_followup executed")

    # escalate_to_human
    state2 = CustomerState(customer_id="test_008")
    assert state2.is_escalated == False
    result = executor.execute(Action.ESCALATE_TO_HUMAN.value, state2)
    assert result.success == True
    assert state2.is_escalated == True
    print("[OK] escalate_to_human executed, flag set")

    # mark_not_interested
    state3 = CustomerState(customer_id="test_009")
    result = executor.execute(Action.MARK_NOT_INTERESTED.value, state3)
    assert result.success == True
    assert result.action == Action.MARK_NOT_INTERESTED.value
    print("[OK] mark_not_interested executed")

    print()


def test_can_execute_check():
    """测试 6: 预检查功能"""
    print("=" * 60)
    print("Test 6: Pre-execution Check (can_execute)")
    print("=" * 60)

    executor = ActionExecutor()
    state = CustomerState(customer_id="test_010")

    # 初始状态，reply 应该可以执行
    can_exec, reason = executor.can_execute(Action.REPLY.value, state)
    assert can_exec == True
    assert reason is None
    print("[OK] can_execute returns True for valid action")

    # 发送一条消息后，立即不能再发送
    executor.execute(Action.REPLY.value, state, reply_content="test")
    can_exec, reason = executor.can_execute(Action.REPLY.value, state)
    assert can_exec == False
    assert "Rate limit" in reason
    print(f"[OK] can_execute detects rate limit: {reason}")

    # escalate 后，其他动作不能执行
    state2 = CustomerState(customer_id="test_011")
    state2.escalate()
    can_exec, reason = executor.can_execute(Action.REPLY.value, state2)
    assert can_exec == False
    assert "escalation" in reason
    print(f"[OK] can_execute detects escalation: {reason}")

    # 非法动作不能执行
    can_exec, reason = executor.can_execute("invalid_action", state)
    assert can_exec == False
    assert "whitelist" in reason
    print(f"[OK] can_execute detects invalid action: {reason}")

    print()


def test_constraint_priority():
    """测试 7: 约束检查优先级"""
    print("=" * 60)
    print("Test 7: Constraint Check Priority")
    print("=" * 60)

    executor = ActionExecutor()
    state = CustomerState(customer_id="test_012")

    # 白名单检查应该优先于其他检查
    # 即使没有 escalate，无效动作也应该被白名单拦截
    try:
        executor.execute("evil_action", state)
        assert False, "Should be rejected by whitelist"
    except SecurityError:
        print("[OK] Whitelist check happens first")

    # escalate 后，白名单检查仍然生效
    state.escalate()
    try:
        executor.execute("evil_action", state)
        assert False, "Should be rejected by whitelist"
    except SecurityError:
        print("[OK] Whitelist check works after escalation")

    # escalate 检查优先于速率限制
    # 先发送一条消息（触发速率限制）
    state2 = CustomerState(customer_id="test_013")
    executor.execute(Action.REPLY.value, state2, reply_content="msg")

    # 然后 escalate
    executor.execute(Action.ESCALATE_TO_HUMAN.value, state2)

    # 尝试 reply 应该被 escalate 检查拦截，而不是速率限制
    try:
        executor.execute(Action.REPLY.value, state2, reply_content="msg2")
        assert False, "Should be rejected by escalate check"
    except EscalatedStateError:
        print("[OK] Escalate check happens before rate limit")

    print()


def run_all_tests():
    """运行所有测试"""
    print("\n")
    print("Starting Task 5 Tests: Action Executor")
    print("=" * 60)
    print()

    try:
        test_action_whitelist()
        test_escalate_silence()
        test_rate_limit_integration()
        test_reply_execution()
        test_other_actions()
        test_can_execute_check()
        test_constraint_priority()

        print("=" * 60)
        print("[SUCCESS] All tests passed!")
        print("=" * 60)
        print("\nTask 5 completed. Ready for Task 6: Agent Controller")

    except AssertionError as e:
        print(f"\n[FAILED] Test failed: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n[ERROR] Runtime error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()

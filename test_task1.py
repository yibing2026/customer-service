"""
任务 1 测试：客户状态管理模块

测试内容：
1. 创建和获取客户状态
2. 添加消息历史
3. 连续问题计数逻辑
4. 强制 escalate 判断
5. escalate 标志设置
6. 动作时间戳记录
"""

import sys
import os

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.insert(0, src_dir)

from core.customer_state import (
    StateManager, CustomerState, Intent, Action, Message, EmotionLevel
)
from datetime import datetime


def test_create_and_get_state():
    """测试 1: 创建和获取客户状态"""
    print("=" * 60)
    print("Test 1: Create and Get Customer State")
    print("=" * 60)

    manager = StateManager()

    # 第一次获取，应该创建新状态
    state1 = manager.get_or_create("customer_001")
    assert state1.customer_id == "customer_001"
    assert state1.is_escalated == False
    assert state1.consecutive_issues == 0
    assert len(state1.message_history) == 0
    print("[OK] Created new customer state successfully")

    # 第二次获取，应该返回相同对象
    state2 = manager.get_or_create("customer_001")
    assert state1 is state2
    print("[OK] Retrieved existing customer state successfully")

    # 获取不存在的客户（使用 get）
    state3 = manager.get("customer_999")
    assert state3 is None
    print("[OK] Get non-existent customer returns None")

    print()


def test_message_history():
    """测试 2: 添加消息历史"""
    print("=" * 60)
    print("Test 2: Message History")
    print("=" * 60)

    manager = StateManager()
    state = manager.get_or_create("customer_002")

    # 添加客户消息
    state.add_message(
        role="customer",
        content="Hello, I want to know about your product",
        intent=Intent.INTERESTED,
        emotion=EmotionLevel.CALM
    )
    assert len(state.message_history) == 1
    assert state.message_history[0].role == "customer"
    assert state.message_history[0].intent == Intent.INTERESTED
    assert state.message_history[0].emotion == EmotionLevel.CALM
    print("[OK] Added customer message successfully")

    # 添加 agent 回复
    state.add_message(
        role="agent",
        content="Hello! I'd be happy to introduce our product..."
    )
    assert len(state.message_history) == 2
    assert state.message_history[1].role == "agent"
    print("[OK] Added agent message successfully")

    print()


def test_consecutive_issues_logic():
    """测试 3: 连续问题计数逻辑（约束 2）"""
    print("=" * 60)
    print("Test 3: Consecutive Issues Logic (Constraint 2)")
    print("=" * 60)

    manager = StateManager()
    state = manager.get_or_create("customer_003")

    # 初始计数为 0
    assert state.consecutive_issues == 0
    print(f"Initial count: {state.consecutive_issues}")

    # 第一次答非所问，计数 +1
    state.increment_consecutive_issues()
    assert state.consecutive_issues == 1
    print(f"After 1st off-topic: {state.consecutive_issues}")

    # 第二次答非所问，计数 +1
    state.increment_consecutive_issues()
    assert state.consecutive_issues == 2
    print(f"After 2nd off-topic: {state.consecutive_issues}")
    print("[OK] Consecutive issues counter increments correctly")

    # 正常消息，计数重置
    state.reset_consecutive_issues()
    assert state.consecutive_issues == 0
    print(f"After reset: {state.consecutive_issues}")
    print("[OK] Counter resets correctly")

    print()


def test_force_escalate_condition():
    """测试 4: 强制 escalate 判断（约束 2）"""
    print("=" * 60)
    print("Test 4: Force Escalate Condition (Constraint 2)")
    print("=" * 60)

    manager = StateManager()
    state = manager.get_or_create("customer_004")

    # 初始不应该 escalate
    assert state.should_force_escalate() == False
    print(f"consecutive_issues=0, should_force_escalate={state.should_force_escalate()}")

    # 计数为 1 时不应该 escalate
    state.increment_consecutive_issues()
    assert state.should_force_escalate() == False
    print(f"consecutive_issues=1, should_force_escalate={state.should_force_escalate()}")

    # 计数为 2 时必须 escalate
    state.increment_consecutive_issues()
    assert state.should_force_escalate() == True
    print(f"consecutive_issues=2, should_force_escalate={state.should_force_escalate()}")
    print("[OK] Force escalate logic is correct")

    print()


def test_escalate_flag():
    """测试 5: escalate 标志设置（约束 3）"""
    print("=" * 60)
    print("Test 5: Escalate Flag (Constraint 3)")
    print("=" * 60)

    manager = StateManager()
    state = manager.get_or_create("customer_005")

    # 初始未 escalate
    assert state.is_escalated == False
    print(f"Initial: is_escalated={state.is_escalated}")

    # 调用 escalate
    state.escalate()
    assert state.is_escalated == True
    print(f"After escalate: is_escalated={state.is_escalated}")
    print("[OK] Escalate flag set correctly")

    print()


def test_action_timestamps():
    """测试 6: 动作时间戳记录（约束 1）"""
    print("=" * 60)
    print("Test 6: Action Timestamps (Constraint 1)")
    print("=" * 60)

    manager = StateManager()
    state = manager.get_or_create("customer_006")

    # 初始无时间戳
    assert len(state.action_timestamps) == 0
    print(f"Initial timestamps: {state.action_timestamps}")

    # 添加时间戳
    import time
    timestamp1 = time.time()
    state.add_action_timestamp(timestamp1)
    assert len(state.action_timestamps) == 1
    print(f"After 1st timestamp: {len(state.action_timestamps)} timestamps")

    # 添加更多时间戳
    timestamp2 = time.time()
    state.add_action_timestamp(timestamp2)
    assert len(state.action_timestamps) == 2
    print(f"After 2nd timestamp: {len(state.action_timestamps)} timestamps")
    print("[OK] Action timestamp recording works correctly")

    print()


def test_state_manager_operations():
    """测试 7: StateManager 操作"""
    print("=" * 60)
    print("Test 7: StateManager Operations")
    print("=" * 60)

    manager = StateManager()

    # 创建多个客户
    state1 = manager.get_or_create("customer_101")
    state2 = manager.get_or_create("customer_102")
    state3 = manager.get_or_create("customer_103")

    # 列出所有客户
    all_states = manager.list_all()
    assert len(all_states) == 3
    print(f"[OK] List all customers: {len(all_states)} customers")

    # 删除一个客户
    manager.delete("customer_102")
    assert manager.get("customer_102") is None
    assert len(manager.list_all()) == 2
    print("[OK] Delete customer successfully")

    # 导出为字典
    state1.increment_consecutive_issues()
    state3.escalate()
    data = manager.to_dict()
    assert "customer_101" in data
    assert "customer_103" in data
    assert data["customer_101"]["consecutive_issues"] == 1
    assert data["customer_103"]["is_escalated"] == True
    print(f"[OK] Export to dict successfully: {list(data.keys())}")

    print()


def run_all_tests():
    """运行所有测试"""
    print("\n")
    print("Starting Task 1 Tests: Customer State Management")
    print("=" * 60)
    print()

    try:
        test_create_and_get_state()
        test_message_history()
        test_consecutive_issues_logic()
        test_force_escalate_condition()
        test_escalate_flag()
        test_action_timestamps()
        test_state_manager_operations()

        print("=" * 60)
        print("[SUCCESS] All tests passed!")
        print("=" * 60)
        print("\nTask 1 completed. Ready for Task 2: Rate Limiter")

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

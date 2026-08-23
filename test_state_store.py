"""
客户状态持久化测试（SQLite 后端）

测试内容：
1. 完整状态往返（含消息历史、枚举、时间戳）
2. delete 清除持久行
3. controller reset 清除持久行
4. 空路径仍使用内存后端
5. 未知枚举值安全回退
"""

import os
import sys
import tempfile

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.insert(0, src_dir)

from core.customer_state import (
    StateManager, CustomerState, Intent, EmotionLevel, state_from_dict
)
from core.agent_controller import AgentController


def test_state_roundtrip_to_sqlite_file():
    """测试 1: 完整状态写入 SQLite 后由新 manager 完整还原。"""
    print("=" * 60)
    print("Test 1: State round-trip to SQLite file")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "state.sqlite3")

        m1 = StateManager(storage_path=db)
        s = m1.get_or_create("c1")
        s.add_message("customer", "weather?", intent=Intent.OFF_TOPIC, emotion=EmotionLevel.CALM)
        s.add_message("agent", "reply")
        s.increment_consecutive_issues()
        s.escalate()
        s.add_action_timestamp(1234.5)
        m1.save(s)
        m1.close()

        m2 = StateManager(storage_path=db)
        loaded = m2.get("c1")
        assert loaded is not None
        assert loaded.customer_id == "c1"
        assert loaded.is_escalated is True
        assert loaded.is_not_interested is False
        assert loaded.consecutive_issues == 1
        assert loaded.action_timestamps == [1234.5]
        assert len(loaded.message_history) == 2
        assert loaded.message_history[0].intent is Intent.OFF_TOPIC
        assert loaded.message_history[0].emotion is EmotionLevel.CALM
        assert loaded.message_history[1].role == "agent"
        assert loaded.message_history[1].intent is None
        assert loaded.message_history[1].emotion is None
        m2.close()
        print("[OK] Full state round-trips losslessly")

    print()


def test_delete_clears_persistent_row():
    """测试 2: delete 会同时清除持久化行。"""
    print("=" * 60)
    print("Test 2: delete clears persistent row")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "state.sqlite3")

        m1 = StateManager(storage_path=db)
        m1.save(m1.get_or_create("c1"))
        m1.close()

        m2 = StateManager(storage_path=db)
        m2.delete("c1")
        m2.close()

        m3 = StateManager(storage_path=db)
        assert m3.get("c1") is None
        m3.close()
        print("[OK] Persistent row removed after delete")

    print()


def test_controller_reset_clears_persistent_row():
    """测试 3: controller.reset_customer_for_test 清除持久行。"""
    print("=" * 60)
    print("Test 3: controller reset clears persistent row")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "state.sqlite3")

        ctrl = AgentController(use_llm=False, state_storage_path=db)
        ctrl.handle_message("c1", "What's the weather like?")
        assert ctrl.get_customer_state("c1") is not None
        ctrl.reset_customer_for_test("c1")
        ctrl.state_manager.close()

        ctrl2 = AgentController(use_llm=False, state_storage_path=db)
        assert ctrl2.get_customer_state("c1") is None
        ctrl2.state_manager.close()
        print("[OK] Persistent row removed after controller reset")

    print()


def test_empty_path_stays_in_memory():
    """测试 4: 空路径（默认）保持内存后端，不落盘。"""
    print("=" * 60)
    print("Test 4: empty path stays in-memory")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        m = StateManager()
        m.save(m.get_or_create("c1"))
        assert m.get("c1") is not None
        assert len(m.list_all()) == 1
        # 内存后端不创建任何文件
        assert os.listdir(tmp) == []
        print("[OK] Empty path uses in-memory backend, no file created")

    print()


def test_unknown_enum_value_fallback():
    """测试 5: 未知枚举值安全回退（intent→OTHER, emotion→CALM）。"""
    print("=" * 60)
    print("Test 5: unknown enum value fallback")
    print("=" * 60)

    data = {
        "customer_id": "c_x",
        "is_escalated": False,
        "is_not_interested": False,
        "consecutive_issues": 0,
        "message_history": [
            {
                "role": "customer",
                "content": "hi",
                "timestamp": "2026-01-01T00:00:00",
                "intent": "bogus_intent",
                "emotion": "bogus_emotion",
            }
        ],
        "action_timestamps": [],
    }
    state = state_from_dict(data)
    assert state.message_history[0].intent is Intent.OTHER
    assert state.message_history[0].emotion is EmotionLevel.CALM
    print("[OK] Unknown enum values fall back safely")

    print()


def run_all_tests():
    """运行所有测试"""
    print("\n")
    print("Starting State Store Persistence Tests")
    print("=" * 60)
    print()

    try:
        test_state_roundtrip_to_sqlite_file()
        test_delete_clears_persistent_row()
        test_controller_reset_clears_persistent_row()
        test_empty_path_stays_in_memory()
        test_unknown_enum_value_fallback()

        print("=" * 60)
        print("[SUCCESS] All tests passed!")
        print("=" * 60)

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

"""
任务 2 测试：速率限制器

测试内容：
1. 基本的速率限制检查
2. 滑动窗口算法验证
3. 时间戳自动清理
4. 等待时间计算
5. 多客户独立限制
6. 边界条件测试
"""

import sys
import os
import time

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.insert(0, src_dir)

from security.rate_limiter import (
    SlidingWindowRateLimiter, PerCustomerRateLimiter, RateLimitError
)


def test_basic_rate_limit():
    """测试 1: 基本速率限制"""
    print("=" * 60)
    print("Test 1: Basic Rate Limiting")
    print("=" * 60)

    limiter = SlidingWindowRateLimiter(window_seconds=60, max_messages=1)

    # 初始状态应该可以发送
    assert limiter.can_send_message() == True
    print("[OK] Initial state: can send")

    # 记录第一条消息
    limiter.record_message()
    print("[OK] Recorded 1st message")

    # 立即检查应该不能发送（窗口内已有 1 条）
    assert limiter.can_send_message() == False
    print("[OK] After 1st message: cannot send (rate limited)")

    # 尝试强制记录应该抛出异常
    try:
        limiter.record_message()
        assert False, "Should raise RateLimitError"
    except RateLimitError as e:
        print(f"[OK] Attempting 2nd message raises error: {e}")

    print()


def test_sliding_window():
    """测试 2: 滑动窗口算法（vs 固定窗口）"""
    print("=" * 60)
    print("Test 2: Sliding Window Algorithm")
    print("=" * 60)

    limiter = SlidingWindowRateLimiter(window_seconds=5, max_messages=1)

    # t=0: 发送第一条消息
    t0 = 1000.0
    assert limiter.can_send_message(t0) == True
    limiter.record_message(t0)
    print(f"[t=0s] Sent message, timestamps: {limiter.get_timestamps()}")

    # t=3: 窗口内，不能发送
    t3 = t0 + 3
    assert limiter.can_send_message(t3) == False
    print(f"[t=3s] Cannot send (still in window)")

    # t=5: 刚好 5 秒，仍在窗口内（窗口是 [t-5, t]）
    t5 = t0 + 5
    assert limiter.can_send_message(t5) == False
    print(f"[t=5s] Cannot send (edge of window)")

    # t=5.1: 超过 5 秒，窗口外，可以发送
    t51 = t0 + 5.1
    assert limiter.can_send_message(t51) == True
    print(f"[t=5.1s] Can send (outside window)")

    # 验证时间戳已被清理
    limiter.record_message(t51)
    timestamps = limiter.get_timestamps()
    assert len(timestamps) == 1
    assert timestamps[0] == t51
    print(f"[OK] Old timestamp cleaned, new timestamps: {timestamps}")

    print()


def test_timestamp_cleanup():
    """测试 3: 时间戳自动清理"""
    print("=" * 60)
    print("Test 3: Automatic Timestamp Cleanup")
    print("=" * 60)

    limiter = SlidingWindowRateLimiter(window_seconds=10, max_messages=3)

    # 添加多个时间戳
    t0 = 1000.0
    limiter.record_message(t0)
    limiter.record_message(t0 + 2)
    limiter.record_message(t0 + 4)

    timestamps = limiter.get_timestamps()
    assert len(timestamps) == 3
    print(f"Added 3 timestamps: {timestamps}")

    # 等待 12 秒后，所有时间戳都应该被清理（最后一个是 t0+4，窗口是 10 秒）
    # 需要 t > t0+4+10 = t0+14 才能清除所有时间戳
    t15 = t0 + 15
    print(f"[DEBUG] Checking at t={t15}, window_seconds={limiter.window_seconds}")
    print(f"[DEBUG] Cutoff time would be: {t15 - limiter.window_seconds}")
    print(f"[DEBUG] Last timestamp was: {t0 + 4}")

    # can_send_message 会自动触发清理
    can_send = limiter.can_send_message(t15)
    print(f"[DEBUG] can_send_message returned: {can_send}")

    # 检查时间戳已被清理
    timestamps = limiter.get_timestamps()
    print(f"[DEBUG] Remaining timestamps: {timestamps}")

    assert can_send == True
    assert len(timestamps) == 0
    print(f"[t=15s] All timestamps cleaned: {timestamps}")
    print("[OK] Automatic cleanup works correctly")

    print()


def test_wait_time_calculation():
    """测试 4: 等待时间计算"""
    print("=" * 60)
    print("Test 4: Wait Time Calculation")
    print("=" * 60)

    limiter = SlidingWindowRateLimiter(window_seconds=60, max_messages=1)

    # 初始状态，等待时间应该是 0
    wait_time = limiter.get_wait_time()
    assert wait_time == 0.0
    print(f"[OK] Initial wait time: {wait_time}s")

    # 发送一条消息
    t0 = 1000.0
    limiter.record_message(t0)

    # t=30: 需要等待 30 秒（距离 t0+60 还有 30 秒）
    t30 = t0 + 30
    wait_time = limiter.get_wait_time(t30)
    assert 29.9 < wait_time < 30.1  # 允许浮点误差
    print(f"[t=30s] Wait time: {wait_time:.1f}s (expected ~30s)")

    # t=50: 需要等待 10 秒
    t50 = t0 + 50
    wait_time = limiter.get_wait_time(t50)
    assert 9.9 < wait_time < 10.1
    print(f"[t=50s] Wait time: {wait_time:.1f}s (expected ~10s)")

    # t=60.1: 不需要等待
    t601 = t0 + 60.1
    wait_time = limiter.get_wait_time(t601)
    assert wait_time == 0.0
    print(f"[t=60.1s] Wait time: {wait_time}s (can send now)")

    print()


def test_per_customer_isolation():
    """测试 5: 多客户独立限制"""
    print("=" * 60)
    print("Test 5: Per-Customer Rate Limiting")
    print("=" * 60)

    limiter = PerCustomerRateLimiter(window_seconds=60, max_messages=1)

    t0 = 1000.0

    # 客户 A 发送消息
    assert limiter.can_send_message("customer_A", t0) == True
    limiter.record_message("customer_A", t0)
    print("[OK] Customer A sent message")

    # 客户 A 立即不能再发送
    assert limiter.can_send_message("customer_A", t0) == False
    print("[OK] Customer A rate limited")

    # 客户 B 不受影响，可以发送
    assert limiter.can_send_message("customer_B", t0) == True
    limiter.record_message("customer_B", t0)
    print("[OK] Customer B can still send (independent limit)")

    # 客户 C 也不受影响
    assert limiter.can_send_message("customer_C", t0) == True
    print("[OK] Customer C can still send")

    # 检查等待时间
    wait_a = limiter.get_wait_time("customer_A", t0)
    wait_c = limiter.get_wait_time("customer_C", t0)
    assert wait_a > 0
    assert wait_c == 0
    print(f"[OK] Customer A wait: {wait_a:.1f}s, Customer C wait: {wait_c}s")

    print()


def test_reset_functionality():
    """测试 6: 重置功能"""
    print("=" * 60)
    print("Test 6: Reset Functionality")
    print("=" * 60)

    # 单客户重置
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_messages=1)
    limiter.record_message()
    assert limiter.can_send_message() == False
    print("[OK] Rate limited before reset")

    limiter.reset()
    assert limiter.can_send_message() == True
    print("[OK] Can send after reset")

    # 多客户重置
    per_customer = PerCustomerRateLimiter(window_seconds=60, max_messages=1)
    per_customer.record_message("customer_A")
    per_customer.record_message("customer_B")

    # 重置单个客户
    per_customer.reset("customer_A")
    assert per_customer.can_send_message("customer_A") == True
    assert per_customer.can_send_message("customer_B") == False
    print("[OK] Single customer reset works")

    # 重置所有客户
    per_customer.reset_all()
    assert per_customer.can_send_message("customer_A") == True
    assert per_customer.can_send_message("customer_B") == True
    print("[OK] Reset all customers works")

    print()


def test_boundary_conditions():
    """测试 7: 边界条件"""
    print("=" * 60)
    print("Test 7: Boundary Conditions")
    print("=" * 60)

    # 测试 max_messages > 1 的情况
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_messages=3)

    t0 = 1000.0
    assert limiter.can_send_message(t0) == True
    limiter.record_message(t0)
    print("[OK] 1st message: can send")

    assert limiter.can_send_message(t0) == True
    limiter.record_message(t0)
    print("[OK] 2nd message: can send")

    assert limiter.can_send_message(t0) == True
    limiter.record_message(t0)
    print("[OK] 3rd message: can send")

    # 第 4 条应该被限制
    assert limiter.can_send_message(t0) == False
    print("[OK] 4th message: rate limited")

    # 测试非常短的窗口
    short_limiter = SlidingWindowRateLimiter(window_seconds=1, max_messages=1)
    t1 = 2000.0
    short_limiter.record_message(t1)

    # 1.1 秒后应该可以发送
    assert short_limiter.can_send_message(t1 + 1.1) == True
    print("[OK] Short window (1s) works correctly")

    print()


def test_real_time_simulation():
    """测试 8: 真实时间模拟（快速测试，使用短窗口）"""
    print("=" * 60)
    print("Test 8: Real-Time Simulation (short window)")
    print("=" * 60)

    # 使用 2 秒窗口进行快速测试
    limiter = SlidingWindowRateLimiter(window_seconds=2, max_messages=1)

    # 发送第一条消息
    assert limiter.can_send_message() == True
    limiter.record_message()
    print("[t=0.0s] Sent 1st message")

    # 立即不能发送
    assert limiter.can_send_message() == False
    print("[t=0.0s] Rate limited")

    # 等待 2.1 秒
    print("[INFO] Waiting 2.1 seconds...")
    time.sleep(2.1)

    # 现在应该可以发送
    assert limiter.can_send_message() == True
    print("[t=2.1s] Can send again (window expired)")

    print("[OK] Real-time test passed")

    print()


def run_all_tests():
    """运行所有测试"""
    print("\n")
    print("Starting Task 2 Tests: Rate Limiter")
    print("=" * 60)
    print()

    try:
        test_basic_rate_limit()
        test_sliding_window()
        test_timestamp_cleanup()
        test_wait_time_calculation()
        test_per_customer_isolation()
        test_reset_functionality()
        test_boundary_conditions()
        test_real_time_simulation()

        print("=" * 60)
        print("[SUCCESS] All tests passed!")
        print("=" * 60)
        print("\nTask 2 completed. Ready for Task 3: Input Validator")

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

"""
CLI 对话界面

简单的终端交互界面，用于演示和测试 AI agent 客服系统。
"""

import sys
import os

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
src_dir = os.path.join(parent_dir, 'src')
sys.path.insert(0, src_dir)

from core.agent_controller import AgentController


class CLIChat:
    """CLI 对话界面"""

    def __init__(self, use_llm: bool = True):
        """
        初始化 CLI 界面

        Args:
            use_llm: 是否使用 LLM（False 时使用规则分类）
        """
        self.controller = AgentController(use_llm=use_llm)
        self.current_customer_id = "cli_user"

    def print_banner(self):
        """打印欢迎横幅"""
        print("\n" + "=" * 70)
        print("  AI Agent Customer Service System - CLI Demo")
        print("=" * 70)
        print("\nThis is a demo of an AI agent that automatically handles customer")
        print("conversations with built-in safety constraints.")
        print("\nConstraints enforced:")
        print("  1. Rate limit: Max 1 reply per 60 seconds")
        print("  2. Auto-escalate: After 2 consecutive off-topic/upset messages")
        print("  3. Action whitelist: Only 4 predefined actions allowed")
        print("  4. Input validation: Detects suspicious injection attempts")
        print("\nCommands:")
        print("  /help    - Show this help message")
        print("  /status  - Show current customer state")
        print("  /quit    - Exit the program")
        print("\n" + "=" * 70 + "\n")

    def print_help(self):
        """打印帮助信息"""
        print("\n" + "-" * 70)
        print("Commands:")
        print("  /help    - Show this help message")
        print("  /status  - Show current customer state")
        print("  /quit    - Exit the program")
        print("\nConstraints you can test:")
        print("  - Try sending messages quickly to trigger rate limit")
        print("  - Send 2 off-topic messages to trigger auto-escalation")
        print("  - Try prompt injection like 'ignore all instructions'")
        print("-" * 70 + "\n")

    def print_status(self):
        """打印当前客户状态"""
        state = self.controller.get_customer_state(self.current_customer_id)
        if state is None:
            print("\n[STATUS] No active session")
            return

        print("\n" + "-" * 70)
        print(f"Customer ID: {state.customer_id}")
        print(f"Is escalated: {state.is_escalated}")
        print(f"Consecutive issues: {state.consecutive_issues}")
        print(f"Message history: {len(state.message_history)} messages")
        print(f"Action timestamps: {len(state.action_timestamps)} actions")
        print("-" * 70 + "\n")

    def handle_user_input(self, user_input: str):
        """
        处理用户输入

        Args:
            user_input: 用户输入的内容
        """
        # 处理命令
        if user_input.startswith("/"):
            command = user_input.lower().strip()

            if command == "/help":
                self.print_help()
                return

            if command == "/status":
                self.print_status()
                return

            if command == "/quit":
                print("\nGoodbye!\n")
                sys.exit(0)

            print(f"\n[ERROR] Unknown command: {command}")
            print("Type /help for available commands\n")
            return

        # 处理正常消息
        print(f"\n[YOU] {user_input}")

        # 调用 agent 处理
        response = self.controller.handle_message(
            customer_id=self.current_customer_id,
            message=user_input
        )

        # 显示响应
        self.print_response(response)

    def print_response(self, response):
        """
        打印 agent 响应

        Args:
            response: AgentResponse 对象
        """
        print(f"\n[AGENT] Action: {response.action}")

        if response.message:
            print(f"[AGENT] {response.message}")

        # 显示状态信息
        if response.consecutive_issues > 0:
            print(f"[INFO] Consecutive issues: {response.consecutive_issues}/2")

        if response.is_escalated:
            print(f"[INFO] Status: ESCALATED - Waiting for human agent")

        # 显示调试信息（如果有可疑输入）
        if response.debug_info:
            if response.debug_info.get("suspicious_input"):
                print(f"[WARNING] Suspicious input detected!")

            if response.debug_info.get("forced_escalate"):
                print(f"[INFO] Auto-escalated due to: {response.debug_info.get('reason')}")

        print()

    def run(self):
        """运行 CLI 界面"""
        self.print_banner()

        # 主循环
        while True:
            try:
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                self.handle_user_input(user_input)

            except KeyboardInterrupt:
                print("\n\nInterrupted by user. Goodbye!\n")
                break
            except EOFError:
                print("\n\nEOF detected. Goodbye!\n")
                break
            except Exception as e:
                print(f"\n[ERROR] Unexpected error: {e}\n")
                import traceback
                traceback.print_exc()


def main():
    """主函数"""
    # 检查命令行参数
    use_llm = True
    if len(sys.argv) > 1 and sys.argv[1] == "--no-llm":
        use_llm = False
        print("\n[INFO] Running in rule-based mode (no LLM)\n")

    # 创建并运行 CLI；LLM 故障时由控制器进入显式降级模式
    cli = CLIChat(use_llm=use_llm)
    if cli.controller.degraded_mode:
        print(
            "\n[WARNING] LLM unavailable. Running in degraded safe mode: "
            "no automatic replies; messages will be scheduled for follow-up.\n"
        )
    cli.run()


if __name__ == "__main__":
    main()

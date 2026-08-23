"""
AI Agent 客服系统 - 主入口

使用方法：
    python main.py              # 使用 LLM 模式（需要配置 API Key）
    python main.py --no-llm     # 使用规则分类模式（不需要 API Key）
    python main.py --web        # 启动网页聊天界面
"""

import argparse
import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def main():
    parser = argparse.ArgumentParser(description="AI Agent customer service demo")
    parser.add_argument("--no-llm", action="store_true", help="使用显式离线规则模式")
    parser.add_argument("--web", action="store_true", help="启动网页聊天界面")
    parser.add_argument("--host", default="127.0.0.1", help="网页监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="网页监听端口，默认 8000")
    args = parser.parse_args()

    if args.web:
        from interface.web_chat import main as web_main
        web_main(use_llm=not args.no_llm, host=args.host, port=args.port)
        return

    from interface.cli_chat import main as cli_main
    # CLI 保持原有交互行为；参数解析后的 --no-llm 通过 sys.argv 传递给旧入口。
    if args.no_llm:
        sys.argv = [sys.argv[0], "--no-llm"]
    else:
        sys.argv = [sys.argv[0]]
    cli_main()


if __name__ == "__main__":
    main()

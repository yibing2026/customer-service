import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LLM API 配置：gemini、deepseek 或 openai-compatible
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

    # Gemini 配置
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # OpenAI 配置（备用）
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # DeepSeek（OpenAI-compatible API）
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # 速率限制配置
    RATE_LIMIT_WINDOW_SECONDS = 60
    RATE_LIMIT_MAX_MESSAGES = 1
    # 留空使用线程安全内存后端；生产环境可配置共享 SQLite 文件路径
    RATE_LIMIT_DB_PATH = os.getenv("RATE_LIMIT_DB_PATH", "")

    # 客户状态持久化配置
    # 留空使用内存后端；生产环境可配置 SQLite 文件路径以跨重启保留客户状态
    CUSTOMER_STATE_DB_PATH = os.getenv("CUSTOMER_STATE_DB_PATH", "")

    # 输入验证配置
    MAX_INPUT_LENGTH = 2000

    # 状态机配置
    MAX_CONSECUTIVE_ISSUES = 2
    # 仅供人工/运维恢复接口使用，不应暴露到客户通道
    HUMAN_OPERATOR_TOKEN = os.getenv("HUMAN_OPERATOR_TOKEN", "")

    # LLM 可靠性配置：初次失败后最多重试 2 次
    LLM_MAX_RETRIES = 2
    LLM_RETRY_BACKOFF_SECONDS = 0.2
    LLM_TIMEOUT_SECONDS = 10


# 关联提示：客户状态与限流是两条相互独立的 SQLite 持久化路径。
# 只配置其一时，跨重启会出现「状态保留但限流丢失」或反之的不一致，
# 因此在配置阶段显式提醒运维/开发者补齐另一项。
if bool(Config.RATE_LIMIT_DB_PATH) != bool(Config.CUSTOMER_STATE_DB_PATH):
    configured = (
        "CUSTOMER_STATE_DB_PATH"
        if Config.CUSTOMER_STATE_DB_PATH
        else "RATE_LIMIT_DB_PATH"
    )
    missing = (
        "RATE_LIMIT_DB_PATH"
        if Config.CUSTOMER_STATE_DB_PATH
        else "CUSTOMER_STATE_DB_PATH"
    )
    print(
        f"[WARNING] 持久化配置不一致：已设置 {configured}，但未设置 {missing}。"
        "两条路径相互独立，跨重启时只有已设置的那项会保留。"
    )

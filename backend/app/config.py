"""应用配置 — 所有 Coze 相关配置项默认留空，真实值仅通过环境变量注入。"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 基础配置 ───────────────────────────────────────────────────
    app_env: str = "development"
    public_base_url: str = "http://localhost:8000"
    # 经营诊断 H5 跳转域名（webview-token 返回 URL 前缀）。真实值经环境变量 H5_BASE_URL 注入。
    h5_base_url: str = "https://wuyou.beautypeaceai.com"
    database_url: str = "sqlite:///./storecoach.db"
    admin_key: str = "dev_admin_key"

    # ── LLM 配置 ──────────────────────────────────────────────────
    llm_provider: str = "local"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"

    # ── 报告存储 ──────────────────────────────────────────────────
    report_storage_path: str = "./storage/reports"

    # ── Coze 公共配置 ─────────────────────────────────────────────
    # 真实值经环境变量注入，不写死、不入库。
    coze_api_base: str = "https://api.coze.cn"
    coze_api_token: str | None = None          # ← 环境变量 COZE_API_TOKEN
    coze_timeout: int = 30                     # 单次请求超时（秒）

    # ── Coze · chat（Bot Chat）────────────────────────────────────
    coze_chat_enabled: bool = False            # 灰度开关，默认关闭走模板
    coze_chat_bot_id: str | None = None        # ← 环境变量 COZE_CHAT_BOT_ID

    # ── Coze · private（Workflow）─────────────────────────────────
    coze_private_enabled: bool = False         # 灰度开关，默认关闭走模板
    coze_private_workflow_id: str | None = None  # ← 环境变量 COZE_PRIVATE_WORKFLOW_ID

    # ── Coze · content（Workflow）─────────────────────────────────
    coze_content_enabled: bool = False         # 灰度开关，默认关闭走模板
    coze_content_workflow_id: str | None = None  # ← 环境变量 COZE_CONTENT_WORKFLOW_ID

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

"""应用配置 — 所有 Coze 相关配置项默认留空，真实值仅通过环境变量注入。"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 基础配置 ───────────────────────────────────────────────────
    app_env: str = "development"
    public_base_url: str = "http://localhost:8000"
    # 经营诊断 H5 跳转域名（webview-token 返回 URL 前缀）。真实值经环境变量 H5_BASE_URL 注入。
    h5_base_url: str = "https://wuyou.beautypeaceai.com"
    database_url: str = "sqlite:///./storecoach.db"
    admin_key: str = "dev_admin_key"  # ← P0B-1 子项：上线前轮换 ADMIN_KEY（.env 注入）

    # ── LLM 配置 ──────────────────────────────────────────────────
    llm_provider: str = "local"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"

    # ── Redis（P0B-1 ticket 存储）───────────────────────────────────
    # 真实值经环境变量 REDIS_URL 注入。
    # 生产格式示例（禁止在此硬编码）：REDIS_URL=redis://:<密码>@127.0.0.1:6379/0
    # 为空时 ticket 降级为内存模式（开发环境可用，生产环境必须配置）。
    redis_url: str = ""

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

    # ── Coze · private（Bot Chat）─────────────────────────────────
    coze_private_enabled: bool = False         # 灰度开关，默认关闭走模板
    coze_private_bot_id: str | None = None  # ← 环境变量 COZE_PRIVATE_BOT_ID

    # ── Coze · content（Bot Chat）─────────────────────────────────
    coze_content_enabled: bool = False         # 灰度开关，默认关闭走模板
    coze_content_bot_id: str | None = None     # ← 环境变量 COZE_CONTENT_BOT_ID

    # ── 报告签名（P0A-4 预留字段，P0B-3 启用）──────────────────────
    # P0B-1：轮换为真实密钥（≥32字符）写入 .env 的 REPORT_SIGN_SECRET。
    # P0B-3：启用 PDF 签名 URL 前必须升级为强校验 field_validator
    #        （拒绝 None / 空 / test / secret / change-me-in-production / 长度<32）。
    report_sign_secret: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

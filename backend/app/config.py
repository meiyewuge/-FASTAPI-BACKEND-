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

    # ── P0B-2 兼容期开关 ──────────────────────────────────────────────
    # True: 旧记录（access_token=NULL）允许无凭证访问（LEGACY_PASS_BY_COMPAT）
    # False: 所有记录必须有凭证（P0B-5 关闭）
    allow_unauthenticated_results: bool = True

    # ── Stage I1 权威身份 ─────────────────────────────────────────────
    # 默认 OFF：旧应用正常启动，身份/Facade 路由不挂载（R1-2）。
    # ON 时启动前校验 4 张身份表就绪，否则 fail-closed，不进入半可用。
    identity_i1_enabled: bool = False
    # 微信配置（真实值仅经环境变量/.env 注入；I0 现场事实：staging/prod 均未配置）。
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    # openid 伪名化独立 HMAC key（≥32 字符）。为空则退化为 salted sha256（仅 dev、identity 关闭时）。
    # 严禁复用微信 secret / Adapter / Caller / Recovery / Vault 根。轮换见 env 模板。
    dm_openid_hmac_key: str = ""
    # R1b: 身份配置统一由 Settings（.env 或环境变量）权威提供，避免 settings 与
    # os.environ 双源漂移。DM_MAIN_BACKEND 必须在身份启用时为真，使 Adapter 密钥根
    # 隔离生效；DM_ADAPTER_SHARED_SECRET 是主后端唯一允许的 DM_* 密钥。
    dm_main_backend: bool = False
    dm_adapter_shared_secret: str = ""
    # R1c: 同一 Settings 源必须贯穿真实 Facade → Adapter → Daily Loop Client 调用链，
    # Adapter 不得再依赖第二套 os.environ 才能工作。feature 开关与上游 base URL 也归
    # Settings。base URL 非密钥。
    dm_daily_loop_adapter_enabled: bool = False
    dm_daily_loop_base_url: str = "http://127.0.0.1:18090"

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

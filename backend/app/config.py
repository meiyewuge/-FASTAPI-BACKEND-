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

    # ── DSM W3-01 权威身份链 (identity I1) ────────────────────────────
    # 默认 OFF：旧应用正常启动，身份路由不挂载。ON 时启动前校验身份表 + 门店
    # 注册表就绪且配置完整独立，否则 fail-closed，不进入半可用状态。
    identity_i1_enabled: bool = False
    # 微信配置（真实值仅经环境变量/.env 注入；生产默认未配置）。
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    # code2session 上游超时（秒）。
    wechat_timeout_seconds: float = 5.0
    # openid 伪名化独立 HMAC key（≥32 字符）。为空则退化为 salted sha256（仅 dev、identity 关闭时）。
    # 严禁复用微信 secret / Adapter 共享密钥 / daily-loop 任一根密钥。
    dm_openid_hmac_key: str = ""
    # 主后端标志：身份启用时必须为真，使密钥根隔离检查生效。
    dm_main_backend: bool = False
    # 主后端唯一允许持有的 DM_* 共享密钥（独立性检查用，不参与本轮登录链）。
    dm_adapter_shared_secret: str = ""
    # 登录限频：窗口秒 + 单 IP 窗口内最大登录尝试次数。
    auth_login_rate_window_seconds: int = 60
    auth_login_rate_max_attempts: int = 10
    # code 防重放短窗口（秒）：窗口内同一 code 再次提交视为重放，拒绝。
    auth_code_replay_window_seconds: int = 300

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

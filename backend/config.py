"""全局配置（pydantic-settings）。从环境变量 / .env 读取。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    app_port: int = 8000

    # 数据库：默认 SQLite，零依赖即可运行；生产可换 PostgreSQL
    database_url: str = "sqlite:///./meiye_v4.db"

    # 多租户：未带租户信息时的默认 tenant
    default_tenant: str = "default"

    # 鉴权（Patch4：邀约码 + JWT）
    jwt_secret: str = "change_me"
    jwt_ttl_seconds: int = 7 * 24 * 3600   # token 有效期（默认 7 天）
    admin_key: str = ""                     # 管理员端点口令（X-Admin-Key）；空=禁用管理端点
    auth_required: bool = True              # 业务 API 是否强制 JWT（测试可关）

    # 视频生成 provider：mock | volcano_seedance | (future) keling / jimeng / runway ...
    video_provider: str = "mock"
    # 真实 provider 失败时是否兜底回退（最终回退到 mock，保证不中断）
    video_fallback: bool = True
    provider_retries: int = 3           # 真实 provider 失败后重试次数（再回退 mock）

    # 真实 HTTP provider 接入参数
    video_api_base: str = ""
    video_api_key: str = ""             # Bearer 模式用的 ARK API Key
    provider_timeout: float = 120.0     # 单次任务最长等待（秒）
    poll_interval: float = 3.0          # 轮询间隔（秒）

    # 火山视频模型
    volc_model: str = "doubao-seedance-2.0-260128"
    # volcano_seedance(Ark, Bearer) 用 video_api_key；volcano_legacy(旧OpenAPI, AK/SK) 用下面
    volc_ak: str = ""                  # legacy: AccessKey
    volc_sk: str = ""                  # legacy: SecretKey
    volc_region: str = "cn-beijing"
    volc_service: str = "ark"

    # mock 成本参数（用于 cost 系统演示）
    cost_per_mother: float = 1.0   # 每条母视频成本
    cost_per_clip: float = 0.1     # 每条裂变片段成本

    # B2：本地视频存储（本地+CDN 双存，download_url 优先本地，根治 24h 过期）
    storage_enabled: bool = False  # ECS 生产置 true（.env），dev/mock 默认 false 不发起下载
    storage_dir: str = "/opt/v4-video-engine/storage/videos"
    # nginx serve 该目录的静态访问基址，如 https://video.beautypeaceai.com/static/videos
    storage_base_url: str = ""

    # B5：分镜脚本生成 script_provider: rule(默认,无依赖) | llm(OpenAI兼容,如DeepSeek/通义)
    script_provider: str = "rule"
    llm_api_base: str = ""              # 如 https://api.deepseek.com/v1
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # Patch2：上传
    upload_dir: str = "/opt/v4-video-engine/uploads"
    upload_base_url: str = ""           # nginx serve，如 https://video.beautypeaceai.com/static/uploads
    max_image_mb: int = 10
    max_video_mb: int = 500

    # V4 P0：批量上传 / 文档 / 批次上限
    max_doc_mb: int = 50                 # doc/docx/zip 单个上限
    max_batch_count: int = 10            # 每类（image/video/file）单批最多文件数
    max_batch_total_gb: float = 2.0      # 单批总量上限（防撑爆 ECS）
    zip_max_entries: int = 1000          # zip 列条目数上限（防 zip bomb）
    zip_max_total_mb: int = 500          # zip 解压后总大小上限（防 zip bomb）

    # V4 P0：临时存储保留与清理（天；0=不自动过期，需手动删）
    mother_retention_days: int = 0       # A台母视频：默认长期保留，可手动删
    viral_retention_days: int = 5        # B台裂变视频：5 天临时
    upload_retention_days: int = 7       # 上传素材：7 天临时

    # V4 P0：批量裂变与 A台防误触上限
    b_batch_total_limit: int = 50        # 单次批量裂变总产出硬上限（P0=50）
    max_a_batch: int = 10                # 一句话/单次最多生成母视频数（防火山误触）


settings = Settings()

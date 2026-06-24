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

    # 鉴权（占位）
    jwt_secret: str = "change_me"

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

    # 本地视频存储（P0：本地+CDN 双存，download_url 优先本地）
    storage_enabled: bool = False   # ECS 生产置 true；mock/dev 保持 false（不发起下载）
    storage_dir: str = "./storage/videos"
    # 静态访问基址（nginx serve 本地文件），如 https://video.beautypeaceai.com/static/videos
    storage_base_url: str = ""
    # 长视频编排：单片段时长（秒），总时长按此切片
    segment_seconds: int = 5


settings = Settings()

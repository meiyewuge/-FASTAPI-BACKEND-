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

    # 视频生成 provider：mock | (future) keling / jimeng / runway ...
    video_provider: str = "mock"

    # mock 成本参数（用于 cost 系统演示）
    cost_per_mother: float = 1.0   # 每条母视频成本
    cost_per_clip: float = 0.1     # 每条裂变片段成本


settings = Settings()

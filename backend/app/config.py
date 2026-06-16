from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    public_base_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./storecoach.db"
    admin_key: str = "dev_admin_key"

    llm_provider: str = "local"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"

    report_storage_path: str = "./storage/reports"

    # Coze 接入（真实值经环境变量注入，不写死、不入库）
    coze_chat_enabled: bool = False
    coze_api_base: str = "https://api.coze.cn"
    coze_api_token: str | None = None
    coze_chat_bot_id: str | None = None
    coze_timeout: int = 30

    # private 阶段（Coze Workflow）
    coze_private_enabled: bool = False
    coze_private_workflow_id: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

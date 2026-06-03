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

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

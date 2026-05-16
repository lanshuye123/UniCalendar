from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "UniCalendar API"
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite+aiosqlite:///./uni_calendar.db"
    DATABASE_URL_SYNC: str = "sqlite:///./uni_calendar.db"
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    AUTH_CODE_EXPIRE_MINUTES: int = 10
    TIMEZONE: str = "Asia/Shanghai"
    CORS_ORIGINS: list[str] = ["*"]
    OAUTH_ISSUER: str = "https://localhost:8000"

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

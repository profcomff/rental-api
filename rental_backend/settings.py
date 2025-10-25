import os
from functools import lru_cache

from pydantic import ConfigDict, PostgresDsn
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""

    DB_DSN: PostgresDsn = "postgresql://postgres@localhost:5432/postgres"
    ROOT_PATH: str = "/" + os.getenv("APP_NAME", "")

    SERVICE_ID: int = os.getenv("SERVICE_ID", -4)  # Указать id сервиса по умолчанию
    RENTAL_SESSION_EXPIRY_IN_MINUTES: int = 15
    RENTAL_SESSION_OVERDUE_IN_HOURS: int = 48  # Указать реальное значение
    RENTAL_SESSION_CREATE_TIME_LIMITER_MINUTES: int = 30
    RENTAL_SESSION_CREATE_NUMBER_LIMITER: int = 2
    CORS_ALLOW_ORIGINS: list[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]
    BASE_OVERDUE: int = 18  # at this amount of hours all items become overdue (at utc format)
    model_config = ConfigDict(case_sensitive=True, env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    return settings

"""
Application configuration using pydantic-settings
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://ledger:ledger123@localhost:5432/ledgerflow"

    # App
    APP_NAME: str = "LedgerFlow"
    DEBUG: bool = False
    SECRET_KEY: str = "change-this-in-production-use-a-real-secret"

    # Pagination
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 500

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

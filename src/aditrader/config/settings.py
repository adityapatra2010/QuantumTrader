"""Centralized configuration and environment settings for AdiTrader."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """System-wide configuration model loaded from environment and .env files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Environment
    aditrader_env: str = Field(default="development", alias="ADITRADER_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    timezone: str = Field(default="Asia/Kolkata", alias="TIMEZONE")

    # Storage & Persistence
    database_url: str = Field(default="sqlite:///runs/aditrader.db", alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    # Broker Authentication (Kotak Neo - Read-Only Data Feeds)
    kotak_consumer_key: str | None = Field(default=None, alias="KOTAK_CONSUMER_KEY")
    kotak_consumer_secret: str | None = Field(default=None, alias="KOTAK_CONSUMER_SECRET")
    kotak_mobile_number: str | None = Field(default=None, alias="KOTAK_MOBILE_NUMBER")
    kotak_password: str | None = Field(default=None, alias="KOTAK_PASSWORD")
    kotak_mpin: str | None = Field(default=None, alias="KOTAK_MPIN")
    kotak_totp_secret: str | None = Field(default=None, alias="KOTAK_TOTP_SECRET")

    # AI Subsystems
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")

    # Risk & Execution Constraints
    initial_capital: float = Field(default=1_000_000.0, alias="INITIAL_CAPITAL")
    max_margin_utilization: float = Field(default=0.85, alias="MAX_MARGIN_UTILIZATION")
    intraday_max_drawdown: float = Field(default=0.05, alias="INTRADAY_MAX_DRAWDOWN")


def get_settings() -> Settings:
    """Return a cached or freshly loaded Settings instance."""
    return Settings()

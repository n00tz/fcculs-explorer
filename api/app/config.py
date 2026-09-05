"""Environment-driven configuration for the API service."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FCCULS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/fcculs"

    # Cookie session signing key. MUST be overridden in any real deployment.
    session_secret: str = "change-me-in-production"
    session_cookie_name: str = "fcculs_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 days

    # Magic-link auth
    magic_link_base_url: str = "http://localhost:8000"
    magic_link_ttl_seconds: int = 60 * 15  # 15 minutes

    # SMTP relay for outbound magic-link emails (BYO relay, no third-party API).
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_address: str = "no-reply@fcculs-explorer.example"

    cors_allow_origins: list[str] = ["*"]


settings = Settings()

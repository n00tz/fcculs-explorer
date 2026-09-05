"""Environment-driven configuration for the notifier service."""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = os.environ.get(
        "FCCULS_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fcculs"
    )
    redis_url: str = os.environ.get("FCCULS_REDIS_URL", "redis://localhost:6379/0")
    queue_name: str = os.environ.get("FCCULS_QUEUE_NAME", "fcculs-notifications")

    smtp_host: str = os.environ.get("FCCULS_SMTP_HOST", "localhost")
    smtp_port: int = int(os.environ.get("FCCULS_SMTP_PORT", "587"))
    smtp_user: str | None = os.environ.get("FCCULS_SMTP_USER")
    smtp_password: str | None = os.environ.get("FCCULS_SMTP_PASSWORD")
    smtp_use_tls: bool = os.environ.get("FCCULS_SMTP_USE_TLS", "true").lower() == "true"
    smtp_from_address: str = os.environ.get(
        "FCCULS_SMTP_FROM_ADDRESS", "no-reply@fcculs-explorer.example"
    )

    max_delivery_attempts: int = int(os.environ.get("FCCULS_MAX_DELIVERY_ATTEMPTS", "5"))


settings = Settings()

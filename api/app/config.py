"""Environment-driven configuration for the API service."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FCCULS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/fcculs"

    # Cookie session signing key. MUST be overridden in any real deployment.
    session_secret: str = "change-me-in-production"
    session_cookie_name: str = "fcculs_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 days

    # Hidden /admin panel session. There is no admin password setting here on
    # purpose: a random superuser password is generated once per API process
    # start and only ever printed to the container's stdout/log (see
    # app.admin_auth) -- it is never stored in the database or config, so
    # the only way to obtain it is having log access to the running
    # container, per the deliberately narrow threat model requested.
    admin_session_cookie_name: str = "fcculs_admin_session"
    admin_session_max_age_seconds: int = 60 * 60 * 12  # 12 hours


    # Magic-link auth.
    #
    # magic_link_base_url is only a FALLBACK: by default (see
    # trust_request_host below) the public base URL used in emailed links
    # is derived from the incoming request's Host/X-Forwarded-* headers, so
    # links work correctly no matter what public hostname/tunnel domain an
    # operator puts in front of the app -- without requiring this value to
    # be kept in sync with it. It's only used when trust_request_host is
    # disabled, or if a request somehow arrives with no Host header at all.
    magic_link_base_url: str = "http://localhost:8000"
    # Derive the public base URL for magic-link emails from the request's
    # Host / X-Forwarded-Host / X-Forwarded-Proto headers (set by Caddy's
    # reverse_proxy and passed through by a Cloudflare Tunnel or any other
    # standard reverse proxy). Set to false to always use
    # magic_link_base_url instead, e.g. if your proxy doesn't forward these
    # headers reliably.
    trust_request_host: bool = True
    magic_link_ttl_seconds: int = 60 * 15  # 15 minutes

    # SMTP relay for outbound magic-link emails (BYO relay, no third-party API).
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_address: str = "no-reply@fcculs-explorer.example"

    # CORS: comma-separated list of origins allowed to make credentialed
    # cross-origin requests (browser sends the session/admin cookie along).
    # MUST be the real public hostname(s) this app is served at (e.g. your
    # Cloudflare Tunnel domain) -- never "*" combined with credentials,
    # since browsers respond to that by reflecting back whatever Origin a
    # requesting page sent, letting any website ride a logged-in user's or
    # admin's session cookie. Change this via FCCULS_CORS_ALLOW_ORIGINS in
    # .env at any time without a rebuild; multiple origins are supported,
    # comma-separated (e.g. "https://a.example,https://b.example").
    cors_allow_origins_raw: str = Field(
        default="https://fcculs-explorer.n00tz.net", validation_alias="FCCULS_CORS_ALLOW_ORIGINS"
    )

    @property
    def cors_allow_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins_raw.split(",") if origin.strip()]

    # Redis-backed rate limiting for abuse-prone unauthenticated endpoints
    # (magic-link request-link, admin login). Redis-backed rather than
    # in-memory so limits survive an API restart/redeploy and are shared
    # across multiple worker processes if ever scaled out.
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_magic_link_max: int = 5
    rate_limit_magic_link_window_seconds: int = 60 * 60  # 1 hour
    rate_limit_admin_login_max: int = 5
    rate_limit_admin_login_window_seconds: int = 60 * 15  # 15 minutes

    # Channel "test send" -- enqueues a real send job onto the same RQ queue
    # the notifier service consumes (must match FCCULS_QUEUE_NAME on the
    # notifier side; see notifier/app/config.py). Rate-limited per-user so
    # this can't be used as a free send-anything relay.
    queue_name: str = "fcculs-notifications"
    test_send_poll_timeout_seconds: float = 8.0
    rate_limit_test_send_max: int = 10
    rate_limit_test_send_window_seconds: int = 60 * 60  # 1 hour


settings = Settings()

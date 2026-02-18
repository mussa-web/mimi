import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


@dataclass(frozen=True)
class Settings:
    app_name: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    login_rate_limit_window_seconds: int
    login_rate_limit_max_attempts: int
    account_lockout_minutes: int
    password_reset_token_expire_minutes: int
    email_verification_token_expire_minutes: int
    email_verification_enabled: bool
    expose_debug_tokens: bool
    issuer: str
    frontend_base_url: str
    cors_origins: tuple[str, ...]
    email_provider: str
    email_from: str
    sendgrid_api_key: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_starttls: bool
    smtp_use_ssl: bool
    smtp_timeout_seconds: int
    cleanup_enabled: bool
    cleanup_interval_minutes: int
    cleanup_unverified_pending_after_hours: int
    database_url: str


settings = Settings(
    app_name=os.getenv("APP_NAME", "Shop Backend Auth API"),
    secret_key=os.getenv("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_32_CHAR_MIN_SECRET_KEY"),
    algorithm=os.getenv("ALGORITHM", "HS256"),
    access_token_expire_minutes=_env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60, min_value=1),
    refresh_token_expire_days=_env_int("REFRESH_TOKEN_EXPIRE_DAYS", 14, min_value=1),
    login_rate_limit_window_seconds=_env_int("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 60, min_value=1),
    login_rate_limit_max_attempts=_env_int("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 10, min_value=1),
    account_lockout_minutes=_env_int("ACCOUNT_LOCKOUT_MINUTES", 15, min_value=1),
    password_reset_token_expire_minutes=_env_int("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", 30, min_value=1),
    email_verification_token_expire_minutes=_env_int("EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES", 30, min_value=1),
    email_verification_enabled=_env_bool("EMAIL_VERIFICATION_ENABLED", False),
    expose_debug_tokens=_env_bool("EXPOSE_DEBUG_TOKENS", True),
    issuer=os.getenv("TOKEN_ISSUER", "shopbackend-api"),
    frontend_base_url=os.getenv("FRONTEND_BASE_URL", "http://localhost:3000"),
    cors_origins=tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ORIGINS", os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")).split(",")
        if origin.strip()
    ),
    email_provider=os.getenv(
        "EMAIL_PROVIDER",
        "sendgrid" if os.getenv("SENDGRID_API_KEY") else ("smtp" if os.getenv("SMTP_HOST") else "console"),
    ).lower(),
    email_from=os.getenv("EMAIL_FROM", "no-reply@shopbackend.local"),
    sendgrid_api_key=os.getenv("SENDGRID_API_KEY", ""),
    smtp_host=os.getenv("SMTP_HOST", ""),
    smtp_port=_env_int("SMTP_PORT", 587, min_value=1),
    smtp_username=os.getenv("SMTP_USERNAME", ""),
    smtp_password=os.getenv("SMTP_PASSWORD", ""),
    smtp_starttls=_env_bool("SMTP_STARTTLS", True),
    smtp_use_ssl=_env_bool("SMTP_USE_SSL", False),
    smtp_timeout_seconds=_env_int("SMTP_TIMEOUT_SECONDS", 15, min_value=1),
    cleanup_enabled=_env_bool("CLEANUP_ENABLED", True),
    cleanup_interval_minutes=_env_int("CLEANUP_INTERVAL_MINUTES", 30, min_value=1),
    cleanup_unverified_pending_after_hours=_env_int(
        "CLEANUP_UNVERIFIED_PENDING_AFTER_HOURS",
        72,
        min_value=1,
    ),
    database_url=os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:rutta25@localhost:2510/RETAILSHOP",
    ),
)

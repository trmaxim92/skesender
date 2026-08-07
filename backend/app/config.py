from functools import lru_cache
from pathlib import Path
import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

_WEAK_SECRET_KEYS = frozenset(
    {
        "change-me",
        "changeme",
        "secret",
        "secret_key",
        "password",
        "django-insecure",
        "dev",
        "development",
        "test",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SkySender"
    debug: bool = True
    secret_key: str
    database_url: str
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173"

    seed_admin_email: str = "admin@order-elite.local"
    seed_admin_password: str = "demo"
    seed_admin_name: str = "Admin"
    seed_max_bot_token: str = ""
    max_api_base: str = "https://platform-api2.max.ru"
    # Max рекомендует сертификат Минцифры; для локальной разработки можно false
    max_api_verify_ssl: bool = False
    max_personal_data_dir: str = str(BACKEND_DIR / "data" / "max_personal")
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_user_data_dir: str = str(BACKEND_DIR / "data" / "telegram_user")
    # Optional proxy for Bot API + MTProto, e.g. socks5://user:pass@host:1080
    # On RU hosts use EU SOCKS or local Cloudflare WARP proxy (see scripts/setup-*.sh)
    telegram_proxy: str = ""
    attachments_dir: str = str(BACKEND_DIR / "data" / "attachments")
    attachment_max_bytes: int = 50 * 1024 * 1024
    # Optional. Enables multi-worker WS fan-out + leader election for pollers/mailing/outbox.
    # Example: redis://127.0.0.1:6379/0
    redis_url: str = ""
    # Web Push (VAPID). Empty = auto-generate keys under data/vapid.json
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_mailto: str = "mailto:admin@skysender.local"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def redis_enabled(self) -> bool:
        return bool((self.redis_url or "").strip())

    @property
    def secret_key_is_weak(self) -> bool:
        key = (self.secret_key or "").strip()
        if len(key) < 24:
            return True
        return key.lower() in _WEAK_SECRET_KEYS


def validate_runtime_settings(settings: Settings | None = None) -> None:
    """Fail fast in production; warn loudly in debug/local."""
    cfg = settings or get_settings()
    if cfg.debug:
        if cfg.secret_key_is_weak:
            logger.warning(
                "DEBUG=true with a weak SECRET_KEY — OK for local only, never deploy like this"
            )
        if not cfg.max_api_verify_ssl:
            logger.warning("MAX_API_VERIFY_SSL=false (local/dev). Set true in production.")
        return

    problems: list[str] = []
    if cfg.secret_key_is_weak:
        problems.append(
            "SECRET_KEY is weak or too short (min 24 chars, not a known placeholder)"
        )
    if cfg.seed_admin_password.strip().lower() in {"demo", "admin", "password", "123456"}:
        problems.append("SEED_ADMIN_PASSWORD looks like a default demo password")
    if problems:
        raise RuntimeError(
            "Refusing to start with DEBUG=false: " + "; ".join(problems)
        )
    if not cfg.max_api_verify_ssl:
        logger.warning(
            "MAX_API_VERIFY_SSL=false while DEBUG=false — TLS to MAX API is not verified"
        )
    if cfg.access_token_expire_minutes > 60 * 24 * 2:
        logger.warning(
            "ACCESS_TOKEN_EXPIRE_MINUTES=%s is long for production; prefer ≤2880 (2d)",
            cfg.access_token_expire_minutes,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

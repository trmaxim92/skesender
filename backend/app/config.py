from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Order Elite"
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
    # Optional MTProto proxy, e.g. socks5://user:pass@host:1080 or http://host:8080
    telegram_proxy: str = ""
    attachments_dir: str = str(BACKEND_DIR / "data" / "attachments")
    attachment_max_bytes: int = 50 * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Central Code"
    imap_host: str
    imap_port: int = 993
    imap_username: str
    imap_password: str
    imap_folder: str = "INBOX"
    code_max_age_minutes: int = 15
    code_ttl_seconds: int = 900
    lookup_rate_limit: int = 10
    lookup_rate_window_seconds: int = 60
    admin_login_rate_limit: int = 5
    admin_login_window_seconds: int = 300
    admin_lockout_seconds: int = 900
    admin_api_rate_limit: int = 120
    admin_api_window_seconds: int = 60
    session_lifetime_seconds: int = 28800
    database_path: str = "data/central-code.sqlite3"
    admin_email: str = "admin@centralcode.local"
    admin_password: str = "CambiaEstaClave123!"
    session_secret: str = "change-this-to-a-long-random-value"
    credentials_key: str = ""
    trusted_hosts: str = "*"
    openapi_enabled: bool = False
    whatsapp_bot_number: str = "573147720880"
    breb_key: str = "1003966611"
    whatsapp_renewal_message: str = (
        "Hola, necesito renovar mi cuenta de {platform}. "
        "Mi celular es {identifier}."
    )
    whatsapp_shop_message: str = (
        "Hola, quiero comprar:\n{items}\nTotal: {total}"
    )

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    @property
    def is_production(self) -> bool:
        return self.app_env.casefold() == "production"

    @property
    def encryption_secret(self) -> str:
        return self.credentials_key.strip() or self.session_secret

    @property
    def uses_insecure_defaults(self) -> bool:
        return (
            self.session_secret == "change-this-to-a-long-random-value"
            or self.admin_password == "CambiaEstaClave123!"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

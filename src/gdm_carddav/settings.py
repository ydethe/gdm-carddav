from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True, env_file=".env", env_file_encoding="utf-8"
    )

    DATABASE_URL: str
    CARDDAV_USERNAME: str = ""
    CARDDAV_PASSWORD: str = ""
    CARDDAV_REALM: str = "gdm_carddav"
    CARDDAV_HOST: str = "0.0.0.0"
    CARDDAV_PORT: int = 8080
    LOGLEVEL: str = "info"


@lru_cache
def get_settings() -> Settings:
    return Settings()

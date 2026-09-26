from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "Recall Me Maybe"
    cors_origins: str = "http://localhost:3000"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    database_url: str = "sqlite:///./data/signal.db"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    exa_api_key: str = ""
    brave_search_api_key: str = ""
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    upload_dir: str = "data/uploads"
    max_upload_bytes: int = 4_000_000

    # Public location is always city-level. Stored coords are snapped to this grid.
    location_grid_decimals: int = 2

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def has_live_search(self) -> bool:
        return bool(self.gemini_api_key or self.exa_api_key or self.brave_search_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()

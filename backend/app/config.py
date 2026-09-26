from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ROOT_DIR = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_DIR / ".env"), str(_BACKEND_DIR / ".env")),
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
    gemini_model: str = "gemini-3.8-flash"
    exa_api_key: str = ""
    brave_search_api_key: str = ""
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_search_model: str = "gpt-4o"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    cognito_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""

    upload_dir: str = "data/uploads"
    max_upload_bytes: int = 4_000_000

    # Public location is always city-level. Stored coords are snapped to this grid.
    location_grid_decimals: int = 2

    # Live bootstrap (hybrid demo path)
    seed_demo: bool = False
    seed_fake_posts: bool = True
    cpsc_recall_limit: int = 25
    fda_food_recall_limit: int = 25
    # Light home scrape — keep Exa/Brave credit burn low.
    home_scrape_products: int = 2
    home_scrape_pages: int = 3
    home_scrape_queries: int = 1
    search_scrape_pages: int = 5
    discovery_cooldown_minutes: int = 20
    # Prefer recent complaints / Ongoing notices (days).
    discovery_recency_days: int = 90

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def resolved_database_url(self) -> str:
        if not self.is_sqlite:
            return self.database_url
        raw = self.database_url.split("///", 1)[-1]
        path = Path(raw)
        if not path.is_absolute():
            path = (_BACKEND_DIR / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"

    @property
    def resolved_upload_dir(self) -> str:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = _BACKEND_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def has_live_search(self) -> bool:
        return bool(
            self.openai_api_key
            or self.gemini_api_key
            or self.exa_api_key
            or self.brave_search_api_key
        )

    @property
    def cognito_configured(self) -> bool:
        return bool(self.cognito_user_pool_id and self.cognito_app_client_id)

    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def cognito_jwks_url(self) -> str:
        return f"{self.cognito_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()

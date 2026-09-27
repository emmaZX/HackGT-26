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
    seed_fake_posts: bool = False
    cpsc_recall_limit: int = 40
    # Light home scrape — default 0 so category Exa is not the home filler.
    home_scrape_products: int = 0
    home_scrape_pages: int = 3
    home_scrape_queries: int = 1
    search_scrape_pages: int = 5
    discovery_cooldown_minutes: int = 20
    # Prefer recent complaints / Ongoing notices (days) — ~2 months.
    discovery_recency_days: int = 60
    # Min URL-backed reports to show an unofficial card (1 = surface the corpus;
    # multi-URL patterns still rank higher via evidence_count / report_count).
    community_min_url_reports: int = 1
    # Wide scrape so specific product patterns can emerge across ~60d.
    community_seed_queries: int = 12
    community_seed_pages: int = 100
    community_seed_per_query: int = 10
    # iWasPoisoned grocery HTTPS crawl — sized for ~2 months of grocery reports.
    iwp_crawl_max_pages: int = 40
    iwp_crawl_max_incidents: int = 400

    # CAERS lags wall-clock; keep a wide lookback so volume spikes still surface.
    caers_lookback_days: int = 270
    caers_fetch_limit: int = 8000
    caers_spike_min_reports: int = 2
    caers_spike_velocity: float = 1.2
    official_recall_max_age_days: int = 90
    fda_food_recall_limit: int = 80
    fsis_recall_limit: int = 100
    outbreak_limit: int = 40

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

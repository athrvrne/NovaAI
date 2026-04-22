"""
Application configuration — loads from .env file
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    secret_key: str = "dev-secret-key"

    # Database
    database_url: str = "sqlite+aiosqlite:///./novaai.db"

    # Admin
    admin_username: str = "admin"
    admin_password: str = "novaai2026"

    # JWT
    jwt_secret: str = "dev-jwt-secret"
    jwt_expire_minutes: int = 480

    # Anthropic
    anthropic_api_key: str = ""

    # SendGrid
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "hello@novaai.com"
    sendgrid_from_name: str = "NovaAI"

    # RSS feeds (pipe-separated for list parsing)
    rss_feeds: str = (
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml|"
        "https://techcrunch.com/category/artificial-intelligence/feed/|"
        "https://feeds.feedburner.com/oreilly/radar"
    )

    # Pipeline
    pipeline_interval_minutes: int = 30
    max_articles_per_run: int = 100
    min_relevance_score: float = 0.6

    @property
    def rss_feed_list(self) -> list[str]:
        return [f.strip() for f in self.rss_feeds.split("|") if f.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

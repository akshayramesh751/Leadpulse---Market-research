"""Configuration settings for the Autonomous Lead Enrichment Agent.

Uses pydantic-settings to automatically load settings from environment
variables or .env file with strongly typed defaults.
"""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Groq LLM settings
    groq_api_key: Optional[str] = None
    groq_model: str = "openai/gpt-oss-120b"

    # Concurrency and scraping limits
    max_concurrency: int = 3
    request_timeout_ms: int = 30000
    max_pages_per_domain: int = 5
    max_tokens_per_domain: int = 6000

    # Search Fallbacks (Phase 7 Bonus)
    serpapi_key: Optional[str] = None
    tavily_api_key: Optional[str] = None

    # Logging and output paths
    log_level: str = "INFO"
    log_file: Path = Path("logs/run.log")
    output_json: Path = Path("outputs/output.json")
    output_csv: Path = Path("outputs/output.csv")
    cost_report_csv: Path = Path("logs/cost_report.csv")


# Global singleton instance
settings = Settings()

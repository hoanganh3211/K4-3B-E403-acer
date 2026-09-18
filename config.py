import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    llm_provider: str = Field(default="openai")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o")
    openai_base_url: str = Field(default="")
    google_api_key: str = Field(default="")
    google_model: str = Field(default="gemini-2.5-flash")
    moderation_model: str = Field(default="")

    tavily_api_key: str = Field(default="")
    jina_api_key: str = Field(default="")
    llm_timeout_seconds: float = Field(default=90, ge=10, le=300)
    search_timeout_seconds: float = Field(default=25, ge=5, le=90)
    max_tokens: int = Field(default=12000, ge=1000, le=32000)
    research_max_chars: int = Field(default=24000, ge=4000, le=60000)
    session_db_path: str = Field(default=str(BASE_DIR / "data" / "sessions.sqlite3"))
    redis_url: str = Field(default="redis://localhost:6379/0")

    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    words_per_minute: int = Field(default=140, ge=60, le=300)
    min_trust_score: int = Field(default=40)
    fuzzy_match_threshold: int = Field(default=75)
    untrusted_xml_tag: str = Field(default="untrusted_content")

    model_config = {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

settings = Settings()

TRUST_CRITERIA = {
    "domain_authority": {"weight": 0.30},
    "recency": {"weight": 0.25},
    "evidence_quality": {"weight": 0.25},
    "author_credibility": {"weight": 0.20},
}

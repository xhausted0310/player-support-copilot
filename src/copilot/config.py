from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://copilot:copilot_dev@localhost:5432/copilot"

    fandom_base_url: str = "https://rainbowsix.fandom.com"
    fandom_request_delay_s: float = 0.5
    fandom_timeout_s: float = 30.0
    user_agent: str = "player-support-copilot/0.1 (pet project; MediaWiki API client)"

    min_text_chars: int = 200
    allowed_languages: tuple[str, ...] = ("en",)
    dedup_threshold: float = 0.85
    dedup_num_perm: int = 128
    dedup_shingle_words: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()

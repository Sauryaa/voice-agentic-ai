from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Voice Health Interview Prototype"
    env: str = Field(default="development", alias="ENV")

    google_cloud_project: str = "voice-agentic-ai-487022"
    google_cloud_location: str = "us-central1"
    gemini_model: str = "gemini-2.5-flash"

    cors_origins: str = "*"

    stt_language_code: str = "en-US"
    silence_timeout_seconds: int = 3

    max_clarifications_per_question: int = 2
    minimum_answer_word_count: int = 5
    gemini_temperature: float = 0.1

    # Optional: when true, the agent can add short acknowledgments before next prompts.
    include_acknowledgment_turns: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        cleaned = (self.cors_origins or "*").strip()
        if cleaned == "*":
            return ["*"]
        return [origin.strip() for origin in cleaned.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

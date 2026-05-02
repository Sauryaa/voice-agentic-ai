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
    silence_timeout_seconds: float = 1.5
    max_recording_seconds: int = 900
    question_bank_path: str = ""

    recaptcha_site_key: str = ""
    recaptcha_expected_action: str = "start_interview"
    recaptcha_min_score: float = 0.5
    recaptcha_verify_timeout_seconds: float = 5.0

    max_clarifications_per_question: int = 2
    minimum_answer_word_count: int = 5
    gemini_temperature: float = 0.1
    gemini_question_temperature: float = 0.3

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

    @property
    def recaptcha_enabled(self) -> bool:
        return bool(self.recaptcha_site_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

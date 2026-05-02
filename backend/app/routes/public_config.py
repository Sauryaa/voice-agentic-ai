from fastapi import APIRouter

from backend.app.config import get_settings
from backend.app.models.schemas import PublicConfig

settings = get_settings()

router = APIRouter(prefix="/api", tags=["public-config"])


@router.get("/public-config", response_model=PublicConfig)
def public_config() -> PublicConfig:
    return PublicConfig(
        app_name=settings.app_name,
        env=settings.env,
        silence_timeout_seconds=settings.silence_timeout_seconds,
        max_recording_seconds=settings.max_recording_seconds,
        recaptcha_enabled=settings.recaptcha_enabled,
        recaptcha_site_key=settings.recaptcha_site_key or None,
        recaptcha_expected_action=settings.recaptcha_expected_action,
    )

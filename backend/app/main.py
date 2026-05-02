from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from backend.app.config import get_settings
from backend.app.limiter import limiter
from backend.app.routes.health import router as health_router
from backend.app.routes.interview import router as interview_router
from backend.app.routes.public_config import router as public_config_router

settings = get_settings()

app = FastAPI(title=settings.app_name)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # Clear and stable 429 payload for frontend/API callers.
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                "Rate limit exceeded for interview requests. "
                "Please wait and try again."
            )
        },
    )


# Register SlowAPI at app startup. Limits are applied per-route via decorators.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

cors_origins = settings.cors_origins_list
allow_all_origins = len(cors_origins) == 1 and cors_origins[0] == "*"

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(public_config_router)
app.include_router(interview_router)

frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

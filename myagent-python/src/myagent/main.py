"""FastAPI application entrypoint."""

from fastapi import FastAPI

from myagent import __version__
from myagent.api.health import router as health_router
from myagent.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated application instance for production and tests."""

    active_settings = settings or get_settings()
    application = FastAPI(
        title=active_settings.app_name,
        version=__version__,
        docs_url="/docs" if active_settings.environment != "production" else None,
        redoc_url=None,
    )
    application.include_router(health_router)
    return application


app = create_app()


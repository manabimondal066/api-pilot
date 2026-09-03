"""
FastAPI application factory for api-pilot backend.

Usage (uvicorn entry point):
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load backend/.env into the process environment before any app import that
# might read os.environ — app.ai.providers.factory and app.config both do.
# load_dotenv() never overrides a variable already set in the environment
# (e.g. one exported by the shell, or set by tests/conftest.py before
# app.main is imported), so this is safe to call unconditionally.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.api import chat as chat_router_module  # noqa: E402
from app.api import endpoints as endpoints_router_module  # noqa: E402
from app.api import environments as environments_router_module  # noqa: E402
from app.api import executions as executions_router_module  # noqa: E402
from app.api import imports as imports_router_module  # noqa: E402
from app.api import suites as suites_router_module  # noqa: E402
from app.api import tests as tests_router_module  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.session import dispose_engine  # noqa: E402

# ---------------------------------------------------------------------------
# Logging — configure structlog once at import time so all modules share it
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO = 20
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event hooks
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # --- Startup ------------------------------------------------------------
    logger.info("database_engine_initialized")
    yield
    # --- Shutdown -----------------------------------------------------------
    await dispose_engine()
    logger.info("database_engine_disposed")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version="0.0.1",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # --- CORS ---------------------------------------------------------------
    origins = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # CRA / alternative dev port
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routers ------------------------------------------------------------
    application.include_router(health_router, prefix=settings.api_prefix)
    application.include_router(
        imports_router_module.router,
        prefix=settings.api_prefix,
        tags=["imports"],
    )
    application.include_router(
        suites_router_module.router,
        prefix=settings.api_prefix,
        tags=["suites"],
    )
    application.include_router(
        endpoints_router_module.router,
        prefix=settings.api_prefix,
        tags=["endpoints"],
    )
    application.include_router(
        tests_router_module.router,
        prefix=settings.api_prefix,
        tags=["tests"],
    )
    application.include_router(
        environments_router_module.router,
        prefix=settings.api_prefix,
        tags=["environments"],
    )
    application.include_router(
        executions_router_module.router,
        prefix=settings.api_prefix,
        tags=["executions"],
    )
    application.include_router(
        chat_router_module.router,
        prefix=settings.api_prefix,
        tags=["chat"],
    )

    logger.info("app_started", env=settings.app_env, prefix=settings.api_prefix)
    return application


# ---------------------------------------------------------------------------
# Module-level app instance — uvicorn target
# ---------------------------------------------------------------------------

app = create_app()

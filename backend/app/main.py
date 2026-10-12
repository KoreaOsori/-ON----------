from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import engine
from app.integrations.redis import close_redis


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    yield
    await close_redis()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="약온 API",
        description="약 정보 챗봇 · 병용 확인 · 주변 약국 · 복약 관리 API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else f"{settings.api_prefix}/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else f"{settings.api_prefix}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()

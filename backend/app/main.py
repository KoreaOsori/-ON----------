from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import engine
from app.integrations.redis import close_redis
from app.llm.v1.api import create_app as create_llm_v1_app
from app.llm.v1.api import lifespan as llm_v1_lifespan
from app.llm.v2.api import create_app as create_llm_v2_app
from app.llm.v2.api import mounted_lifespan as llm_v2_lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        # Mounted sub-app lifespans must be entered explicitly.
        async with llm_v1_lifespan(app.state.llm_v1_app), llm_v2_lifespan(app.state.llm_v2_app):
            yield
    finally:
        try:
            await close_redis()
        finally:
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
    app.state.llm_v1_app = create_llm_v1_app()
    app.mount("/api/llm/v1", app.state.llm_v1_app)
    # v2: LLM_V2_API_KEY 가 없거나 초기화에 실패하면 v2 경로만 503 이고 백엔드는 계속 뜬다.
    app.state.llm_v2_app = create_llm_v2_app(route_prefix="", require_api_key=True)
    app.mount("/api/llm/v2", app.state.llm_v2_app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()

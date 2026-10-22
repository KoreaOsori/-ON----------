import logging
import secrets
from contextlib import asynccontextmanager

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.security import APIKeyHeader
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .aws_auth import RoleCredentialsError
from .bedrock import Bedrock
from .config import Settings
from .database import DatabaseConnectionError, create_database_engine
from .repository import DataUnavailable, Repository
from .schemas import AskRequest, AskResponse
from .service import Service

logger = logging.getLogger(__name__)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def authorize(request: Request, key: str | None = Depends(api_key_header)):
    expected = request.app.state.llm_settings.api_key
    if expected and (not key or not secrets.compare_digest(key, expected.get_secret_value())):
        raise HTTPException(401, "올바른 X-API-Key가 필요합니다.")


router = APIRouter(tags=["LLM v1"], dependencies=[Depends(authorize)])


@router.get("/models")
async def models(request: Request):
    settings = request.app.state.llm_settings
    return {"default": settings.default_model, "models": {
        "sonnet": settings.sonnet_model_id, "haiku": settings.haiku_model_id}}


@router.post("/ask", response_model=AskResponse,
             responses={401: {"model": AskResponse}, 422: {"model": AskResponse}, 503: {"model": AskResponse}})
async def ask(body: AskRequest, request: Request):
    settings = request.app.state.llm_settings
    try:
        async with request.app.state.llm_engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                await conn.execute(text("SET LOCAL statement_timeout = '15s'"))
                return await Service(Repository(conn, settings), request.app.state.llm_bedrock, settings).ask(body)
    except (DataUnavailable, DatabaseConnectionError) as error:
        raise HTTPException(503, str(error)) from None
    except RoleCredentialsError as error:
        raise HTTPException(503, str(error)) from None
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "unknown")
        logger.warning("LLM v1 Bedrock failure: %s", code)
        raise HTTPException(503, "Bedrock 호출 실패: IAM 권한, 리전, 모델 ID 및 사용 한도를 확인하세요.") from None
    except (BotoCoreError, SQLAlchemyError, OSError, ValueError, KeyError):
        # Do not log question text, credentials, SQL parameters, or raw AWS responses.
        logger.warning("LLM v1 dependency unavailable")
        raise HTTPException(503, "DB 또는 Bedrock 연결·설정을 확인하세요.") from None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.llm_settings = settings
    app.state.llm_engine = create_database_engine(settings)
    app.state.llm_bedrock = Bedrock(settings)
    try:
        yield
    finally:
        await app.state.llm_engine.dispose()


def create_app(*, route_prefix: str = "") -> FastAPI:
    application = FastAPI(
        title="약·건강기능식품 LLM v1 테스트", version="1.0.0", lifespan=lifespan,
        docs_url="/docs", openapi_url="/openapi.json", redoc_url=None,
    )
    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        messages = {401: "접근 인증을 확인한 뒤 다시 시도해 주세요.",
                    404: "요청하신 주소를 찾지 못했어요.",
                    405: "요청 방식을 확인해 주세요."}
        body = AskResponse(status="error", answer=messages.get(error.status_code,
            "지금은 정보를 확인하는 데 문제가 있어요. 잠시 후 다시 시도해 주세요."))
        return JSONResponse(status_code=error.status_code, content=body.model_dump(), headers=error.headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse(status_code=422, content=AskResponse(status="error",
            answer="질문과 제품명 목록의 입력 형식을 확인해 주세요. 제품명은 문자열 목록으로 입력해 주세요.").model_dump())

    application.include_router(router, prefix=route_prefix)
    return application


# Preserve existing standalone :8011/llm/v1/* clients.
app = create_app(route_prefix="/llm/v1")

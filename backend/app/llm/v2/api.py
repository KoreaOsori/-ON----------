"""v2 HTTP API (FastAPI). 에이전트(`agent.py`)를 서비스로 노출한다.

    python -m uvicorn app.llm.v2.api:app --app-dir backend --host 127.0.0.1 --port 8012

- 엔드포인트: POST /llm/v2/ask (질문), GET /llm/v2/models (설정 확인, 인증), GET /llm/v2/health (생존 확인, 인증 없음).
- 서버는 대화 상태를 저장하지 않는다. 제품 후보가 여럿이라 status 가 needs_clarification 이면 candidates 를 사용자에게 보여 주고,
  사용자가 고른 product_key 를 넣어 같은 질문을 다시 보낸다.
- 보안: LLM_V2_API_KEY 가 있으면 X-API-Key 헤더가 일치해야 한다(상수 시간 비교). 없으면 키 없이 열리므로 localhost 로만 띄운다.
  질문·프로필 내용과 비밀값은 로그에 남기지 않는다. 오류 응답에는 내부 메시지를 담지 않는다.
- 독립 앱으로 실행하거나(위 명령), 백엔드 앱에 v1 처럼 mount 한다: `create_app(route_prefix="", require_api_key=True)` 를
  `/api/llm/v2` 에 mount 하고, 부모 lifespan 에서 `mounted_lifespan(child)` 를 연다(backend/app/main.py).
  라우터만 다른 앱에 붙이면 lifespan 이 설정하는 app.state 가 없어 동작하지 않는다.
- mount 모드의 안전장치: ① LLM_V2_API_KEY 가 없으면 공개 경로로 서비스하지 않고 503 을 돌려준다(Bedrock 비용 보호).
  ② v2 초기화가 실패해도 백엔드 전체는 계속 뜨고 v2 경로만 503 이다(웹 서비스를 v2 때문에 내리지 않는다).
"""
import asyncio
import logging
import secrets
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.llm.v2.agent import DrugInfoAgent, build_agent
from app.llm.v2.config import ConfigError, V2Settings
from app.llm.v2.db import safe_error_name
from app.llm.v2.prompts import ERROR_ANSWER, TIMEOUT_ANSWER
from app.llm.v2.search import PRODUCT_KEY_PATTERN

logger = logging.getLogger(__name__)

MAX_QUESTION_FIELD = 1000  # 스키마 상한. 실제 허용 길이는 설정(max_question_chars)이 정한다.
BUSY_MESSAGE = "지금 요청이 많아 바로 답변드리기 어려워요. 잠시 후 다시 시도해 주세요."

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_FIELD, description="사용자 질문(자연어)")
    product_key: str | None = Field(
        None, max_length=120, description="needs_clarification 에서 사용자가 고른 후보의 product_key. 예: drug:195700010"
    )
    profile_context: str | None = Field(
        None, max_length=1000, description="사용자 정보(나이·복용 중인 약 등). 모델에는 데이터로만 전달된다."
    )

    @field_validator("product_key")
    @classmethod
    def valid_product_key(cls, value: str | None) -> str | None:
        if value is not None and not PRODUCT_KEY_PATTERN.match(value):
            raise ValueError("product_key 형식이 올바르지 않습니다.")
        return value


class Candidate(BaseModel):
    product_key: str
    product_name: str
    manufacturer: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class AskResponse(BaseModel):
    status: Literal["done", "no_evidence", "needs_clarification", "crisis", "empty", "refusal", "budget"] = Field(
        description="done=근거 있는 답변, no_evidence=근거 없음(고정 안내), needs_clarification=제품 확인 필요, "
        "crisis=위기 안내, empty=빈 질문, refusal/budget=모델 거절·한도 초과(고정 안내)"
    )
    answer: str
    grounded: bool = Field(description="검색·조회 근거가 있는 답변인가")
    emergency: bool = Field(description="응급 표현이 감지되어 안내 문구가 앞에 붙었는가")
    sources: list[str] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    rounds: int = 0
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    model_id: str


async def ensure_ready(request: Request) -> None:
    """mount 모드에서 초기화에 실패했거나 아직 시작 전이면 내부 속성 오류 대신 503 을 돌려준다."""
    state = request.app.state
    if getattr(state, "llm_unavailable", False) or getattr(state, "llm_agent", None) is None:
        raise HTTPException(503, ERROR_ANSWER)


async def authorize(request: Request, key: str | None = Depends(api_key_header)) -> None:
    expected = request.app.state.llm_settings.api_key
    if expected and (not key or not secrets.compare_digest(key.encode(), expected.encode())):
        raise HTTPException(401, "올바른 X-API-Key가 필요합니다.")


# 경로 접두사는 create_app(route_prefix=...) 가 붙인다(독립 실행은 /llm/v2, 백엔드 mount 는 빈 접두사).
router = APIRouter(tags=["LLM v2"], dependencies=[Depends(ensure_ready), Depends(authorize)])
public_router = APIRouter(tags=["LLM v2"], dependencies=[Depends(ensure_ready)])


@public_router.get("/health")
async def health() -> dict[str, str]:
    """프로세스 생존 확인. DB·Bedrock 은 확인하지 않는다."""
    return {"status": "ok"}


@router.get("/models")
async def models(request: Request) -> dict[str, Any]:
    settings: V2Settings = request.app.state.llm_settings
    agent: DrugInfoAgent = request.app.state.llm_agent
    return {
        "default": settings.default_model,
        "model_id": settings.resolved_model_id,
        "models": {"haiku": settings.haiku_model_id, "sonnet": settings.sonnet_model_id},
        "tools": agent.tool_names,
        "max_distance": settings.max_distance,
    }


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request) -> AskResponse:
    state = request.app.state
    settings: V2Settings = state.llm_settings
    if len(body.question) > settings.max_question_chars:
        raise HTTPException(422, f"질문은 {settings.max_question_chars}자 이하로 입력해 주세요.")

    gate: asyncio.Semaphore = state.llm_gate
    try:
        await asyncio.wait_for(gate.acquire(), timeout=settings.api_queue_seconds)
    except asyncio.TimeoutError:
        raise HTTPException(
            503, BUSY_MESSAGE, headers={"Retry-After": str(max(1, int(settings.api_queue_seconds)))}
        ) from None
    try:
        result = await state.llm_agent.run(body.question, body.profile_context, body.product_key)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 질문·비밀값을 남기지 않는다.
        logger.error("ask 처리 실패: %s", safe_error_name(exc))
        raise HTTPException(503, ERROR_ANSWER) from None
    finally:
        gate.release()

    # 서비스 장애는 HTTP 오류로, 정책에 따른 안내(근거 없음·되묻기·위기 등)는 200 으로 돌려준다.
    if result.stop_reason == "error":
        raise HTTPException(503, ERROR_ANSWER)
    if result.stop_reason == "timeout":
        raise HTTPException(504, TIMEOUT_ANSWER)

    logger.info(
        "ask status=%s rounds=%d tools=%d latency=%.1fs",
        result.stop_reason, result.rounds, len(result.tools_used), result.elapsed_seconds,
    )
    return AskResponse(
        status=result.stop_reason,
        answer=result.answer,
        grounded=result.grounded,
        emergency=result.emergency,
        sources=result.sources,
        candidates=[Candidate(**c) for c in result.candidates],
        tools_used=result.tools_used,
        rounds=result.rounds,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
        latency_ms=round(result.elapsed_seconds * 1000),
        model_id=settings.resolved_model_id,
    )


def create_app(
    settings: V2Settings | None = None,
    agent: DrugInfoAgent | None = None,
    *,
    route_prefix: str = "/llm/v2",
    require_api_key: bool = False,
) -> FastAPI:
    """앱 팩토리. settings/agent 를 주면(테스트) 그대로 쓰고, 없으면 시작할 때 환경변수로 만든다.

    route_prefix    : 독립 실행은 "/llm/v2"(기존 경로 유지), 백엔드에 mount 할 때는 ""(mount 경로가 접두사).
    require_api_key : True 면 LLM_V2_API_KEY 가 없을 때 시작을 거부한다(공개 경로용).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings or V2Settings.from_env()  # 설정 오류는 여기서 시작을 막는다(메시지에 비밀값 없음)
        if require_api_key and not resolved.api_key:
            raise ConfigError("공개 경로로 서비스하려면 LLM_V2_API_KEY 환경변수가 필요합니다.")
        app.state.llm_settings = resolved
        app.state.llm_agent = agent or build_agent(resolved)
        app.state.llm_gate = asyncio.Semaphore(resolved.api_max_concurrency)
        if not resolved.api_key:
            logger.warning("LLM_V2_API_KEY 가 없어 인증 없이 열려 있습니다. localhost 로만 사용하세요.")
        try:
            yield
        finally:
            await app.state.llm_agent.aclose()

    app = FastAPI(
        title="약온 LLM v2", version="2.0.0", lifespan=lifespan,
        docs_url="/docs", openapi_url="/openapi.json", redoc_url=None,
    )
    app.include_router(public_router, prefix=route_prefix)
    app.include_router(router, prefix=route_prefix)
    return app


@asynccontextmanager
async def mounted_lifespan(child: FastAPI):
    """부모(백엔드) 앱의 lifespan 안에서 mount 한 v2 앱의 시작·종료를 수행한다(mount 한 앱의 lifespan 은 자동으로 돌지 않는다).

    v2 초기화가 실패해도 예외를 밖으로 내보내지 않는다: 백엔드 전체는 계속 뜨고 v2 경로는 503 을 돌려준다.
    원인은 예외 클래스 이름만 로그에 남긴다(비밀값 비노출).
    """
    stack = AsyncExitStack()
    try:
        await stack.enter_async_context(child.router.lifespan_context(child))
    except Exception as exc:  # noqa: BLE001
        child.state.llm_unavailable = True
        # ConfigError 의 메시지는 설정 안내뿐이라(비밀값 없음) 그대로 남기고, 그 밖의 예외는 클래스 이름만 남긴다.
        reason = str(exc) if isinstance(exc, ConfigError) else safe_error_name(exc)
        logger.error("LLM v2 시작 실패(백엔드는 계속 실행, v2 경로는 503): %s", reason)
    try:
        yield
    finally:
        await stack.aclose()


app = create_app()

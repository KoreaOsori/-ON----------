"""Claude 호출 어댑터 (강의의 llm.py 에 해당).

루프는 'create(**kwargs) -> response' 비동기 함수 하나만 안다 → 테스트에서 가짜로 교체하기 쉽다.

provider
- bedrock (기본): anthropic.AsyncAnthropicBedrock — InvokeModel 기반. 현재 EC2 역할(bedrock:InvokeModel)로 호출 가능한 쪽.
- mantle : anthropic.AsyncAnthropicBedrockMantle — 기존 backend/app/integrations/bedrock.py 와 같은 엔드포인트.
           IAM 에 bedrock-mantle:CreateInference 가 필요하다(현재 EC2 역할에는 없음).

미검증: 두 엔드포인트 모두 '도구 호출(tools / tool_use)' 지원 여부와 모델 ID 는 실제 호출로 확인해야 한다.
모델 ID 기본값은 config.py(v1 설정과 같은 us. 추론 프로파일 ID)이며 LLM_V3_* 환경변수로 바꿀 수 있다.
"""
import logging
from typing import Any, Awaitable, Callable

from app.llm.v3.config import V3Settings

CreateMessage = Callable[..., Awaitable[Any]]

logger = logging.getLogger(__name__)


def wrap_create(create: CreateMessage, model_id: str, max_tokens: int, thinking_disabled: bool) -> CreateMessage:
    """모델 ID·max_tokens 를 붙이고, 요청하면 thinking 을 끈다. 엔드포인트가 thinking 옵션을 거부하면 끄고 한 번 다시 시도한다."""
    disable = thinking_disabled

    async def create_message(**kwargs: Any) -> Any:
        nonlocal disable
        extra = {"thinking": {"type": "disabled"}} if disable else {}
        try:
            return await create(model=model_id, max_tokens=max_tokens, **extra, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if not (disable and "thinking" in str(exc).lower()):
                raise
            logger.warning("thinking 옵션을 지원하지 않아 끕니다: %s", type(exc).__name__)
            disable = False
            return await create(model=model_id, max_tokens=max_tokens, **kwargs)

    return create_message


def build_create_message(settings: V3Settings) -> CreateMessage:
    model_id = settings.resolved_model_id

    if settings.llm_provider == "mantle":
        from anthropic import AsyncAnthropicBedrockMantle

        client = AsyncAnthropicBedrockMantle(aws_region=settings.region)
        create = client.beta.messages.create  # 기존 래퍼와 동일하게 beta 네임스페이스 사용
    else:
        from anthropic import AsyncAnthropicBedrock

        client = AsyncAnthropicBedrock(aws_region=settings.region)
        create = client.messages.create

    return wrap_create(create, model_id, settings.llm_max_tokens, settings.thinking_disabled)

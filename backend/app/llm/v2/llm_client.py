"""Claude 호출 어댑터 (강의의 llm.py 에 해당).

루프는 'create(**kwargs) -> response' 비동기 함수 하나만 안다 → 테스트에서 가짜로 교체하기 쉽다.

provider
- bedrock (기본): anthropic.AsyncAnthropicBedrock — InvokeModel 기반. 현재 EC2 역할(bedrock:InvokeModel)로 호출 가능한 쪽.
- mantle : anthropic.AsyncAnthropicBedrockMantle — 기존 backend/app/integrations/bedrock.py 와 같은 엔드포인트.
           IAM 에 bedrock-mantle:CreateInference 가 필요하다(현재 EC2 역할에는 없음).

미검증: 두 엔드포인트 모두 '도구 호출(tools / tool_use)' 지원 여부와 모델 ID 는 실제 호출로 확인해야 한다.
모델 ID 기본값은 config.py(v1 설정과 같은 us. 추론 프로파일 ID)이며 LLM_V2_* 환경변수로 바꿀 수 있다.
"""
from typing import Any, Awaitable, Callable

from app.llm.v2.config import V2Settings

CreateMessage = Callable[..., Awaitable[Any]]


def build_create_message(settings: V2Settings) -> CreateMessage:
    model_id = settings.resolved_model_id

    if settings.llm_provider == "mantle":
        from anthropic import AsyncAnthropicBedrockMantle

        client = AsyncAnthropicBedrockMantle(aws_region=settings.region)
        create = client.beta.messages.create  # 기존 래퍼와 동일하게 beta 네임스페이스 사용
    else:
        from anthropic import AsyncAnthropicBedrock

        client = AsyncAnthropicBedrock(aws_region=settings.region)
        create = client.messages.create

    async def create_message(**kwargs: Any) -> Any:
        return await create(model=model_id, max_tokens=settings.llm_max_tokens, **kwargs)

    return create_message

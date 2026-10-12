"""Amazon Bedrock 의 Claude 호출 래퍼.

- 인증: ECS Task Role(IAM) → 별도 API 키 불필요. 로컬은 AWS 프로필/환경변수 자격증명 사용.
- 안전 분류기가 요청을 거절(stop_reason == "refusal")하면 BetaRefusalFallbackMiddleware 가
  bedrock_fallback_model_id 모델로 같은 요청을 재시도한다. (Bedrock 은 서버측 fallbacks 파라미터 미지원)
"""

import logging
from functools import lru_cache
from typing import Any

import anthropic
from anthropic import AsyncAnthropicBedrockMantle, BetaRefusalFallbackMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)


class ClaudeUnavailableError(Exception):
    """Bedrock 호출 실패 (일시적 장애/한도 초과 등)"""


@lru_cache
def get_claude_client() -> AsyncAnthropicBedrockMantle:
    middleware = (
        [BetaRefusalFallbackMiddleware([{"model": settings.bedrock_fallback_model_id}])]
        if settings.bedrock_fallback_model_id
        else []
    )
    return AsyncAnthropicBedrockMantle(aws_region=settings.bedrock_region, middleware=middleware)


async def create_message(
    *,
    system: str,
    content: str | list[dict[str, Any]],
) -> str | None:
    """단일 턴 요청을 보내고 텍스트 응답을 반환한다. 모델이 끝내 거절하면 None.

    참고: Bedrock(Mantle) 엔드포인트는 structured outputs(output_config.format)를 지원하지 않는다.
    """
    output_config: dict[str, Any] = {"effort": settings.bedrock_effort}
    try:
        response = await get_claude_client().beta.messages.create(
            model=settings.bedrock_model_id,
            max_tokens=settings.bedrock_max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config=output_config,
        )
    except anthropic.RateLimitError as error:
        logger.warning("Bedrock 요청 한도 초과: %s", error)
        raise ClaudeUnavailableError from error
    except anthropic.APIStatusError as error:
        logger.error("Bedrock API 오류 status=%s: %s", error.status_code, error)
        raise ClaudeUnavailableError from error
    except anthropic.APIConnectionError as error:
        logger.error("Bedrock 연결 실패: %s", error)
        raise ClaudeUnavailableError from error

    if response.stop_reason == "refusal":
        logger.info("Claude 응답 거절: %s", response.stop_details)
        return None
    return "".join(block.text for block in response.content if block.type == "text")

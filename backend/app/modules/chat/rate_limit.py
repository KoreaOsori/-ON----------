"""비회원 일일 질문 횟수 제한 (Redis 카운터, KST 기준 자정 초기화)"""

import contextlib
import logging
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


class GuestQuota:
    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    def _key(client_id: str) -> str:
        return f"chat:guest:{datetime.now(KST):%Y%m%d}:{client_id}"

    async def consume(self, client_id: str) -> int | None:
        """질문 1회를 차감하고 남은 횟수를 반환한다. 한도 초과 시 -1.
        Redis 장애 시에는 서비스 가용성을 우선해 제한 없이 통과(None)시킨다."""
        limit = settings.guest_daily_question_limit
        key = self._key(client_id)
        try:
            used = await self.redis.incr(key)
            if used == 1:
                await self.redis.expire(key, int(timedelta(days=1, hours=1).total_seconds()))
        except RedisError as error:
            logger.warning("비회원 질문 제한 확인 실패(통과 처리): %s", error)
            return None
        if used > limit:
            return -1
        return limit - used

    async def refund(self, client_id: str) -> None:
        """답변 생성에 실패했을 때 차감한 횟수를 되돌린다."""
        with contextlib.suppress(RedisError):
            await self.redis.decr(self._key(client_id))

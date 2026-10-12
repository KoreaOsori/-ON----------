import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.integrations.redis import get_redis

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", summary="헬스체크 (ALB 대상 그룹용, 의존성 미확인)")
async def health():
    return {"status": "ok", "env": settings.app_env}


@router.get("/health/ready", summary="준비 상태 (DB · Redis 연결 확인)")
async def readiness(response: Response):
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as error:  # noqa: BLE001 - 헬스체크는 모든 오류를 실패로 보고한다
        logger.warning("DB 헬스체크 실패: %s", error)
        checks["database"] = "error"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as error:  # noqa: BLE001
        logger.warning("Redis 헬스체크 실패: %s", error)
        checks["redis"] = "error"
    healthy = "error" not in checks.values()
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", "checks": checks}

"""pill_model 워커 호출 (알약 식별 /pill/*, 처방전 인식 /rx/*).

워커는 별도 EC2 에서 돌고 백엔드 SG 에서 오는 8000 만 받는다. 인증은 X-Worker-Token 헤더.
사진은 넘기지 않고 S3 object_key 만 넘긴다 (워커가 업로드 버킷에서 직접 읽음).
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class WorkerError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# 워커 응답 코드 → 프런트에 돌려줄 코드. 401(토큰 불일치)은 서버 설정 문제라 502 로 숨긴다
_PASS = {400, 404, 410, 413, 422, 502, 503}


def owner_of(object_key: str) -> str:
    """presign 형식 {purpose}/YYYY/MM/DD/{owner}/{uuid}.ext 의 owner (회원 ID 또는 guest)"""
    parts = object_key.split("/")
    return parts[4] if len(parts) == 6 else ""


async def call(path: str, payload: dict) -> dict:
    if not settings.pill_worker_url or not settings.pill_worker_token:
        raise WorkerError(503, "not_configured", "사진 인식 서버가 아직 연결되지 않았어요.")
    try:
        async with httpx.AsyncClient(
            base_url=settings.pill_worker_url, timeout=settings.pill_worker_timeout_seconds
        ) as client:
            response = await client.post(
                path, json=payload, headers={"X-Worker-Token": settings.pill_worker_token}
            )
    except httpx.TimeoutException as error:
        raise WorkerError(
            504, "timeout", "인식 시간이 너무 오래 걸려요. 잠시 후 다시 시도해 주세요."
        ) from error
    except httpx.HTTPError as error:
        logger.warning("pill worker 연결 실패: %s", type(error).__name__)
        raise WorkerError(502, "unreachable", "사진 인식 서버에 연결할 수 없어요.") from error

    if response.status_code >= 400:
        detail = (
            response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        ).get("detail")
        code = detail.get("code", "error") if isinstance(detail, dict) else "error"
        message = (
            detail.get("message", "사진 인식에 실패했어요.")
            if isinstance(detail, dict)
            else "요청 형식이 맞지 않아요."
        )
        status = response.status_code if response.status_code in _PASS else 502
        logger.warning("pill worker %s → %s %s", path, response.status_code, code)
        raise WorkerError(status, code, message)
    return response.json()

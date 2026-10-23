from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import OptionalUser
from app.modules.pill import service
from app.modules.pill.schemas import (
    PillAnalyzeRequest,
    PillConfirmRequest,
    PillImprintChoiceRequest,
    PillRefineRequest,
    PillRejectRequest,
)

router = APIRouter(prefix="/pill", tags=["pill"])


async def _forward(path: str, payload) -> dict[str, Any]:
    try:
        return await service.call(path, payload.model_dump(by_alias=True))
    except service.WorkerError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message}) from error


@router.post("/analyze", summary="알약 사진(앞·뒤) 식별 → 후보와 다음 대화 단계")
async def analyze(payload: PillAnalyzeRequest, user: OptionalUser):
    # 업로드(presign)와 같은 규칙: 회원은 본인 경로, 비회원은 guest 경로만
    owner = str(user.id) if user else "guest"
    if any(service.owner_of(key) != owner for key in (payload.front_key, payload.back_key) if key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "본인이 업로드한 파일만 인식할 수 있습니다.")
    return await _forward("/pill/analyze", payload)


@router.post("/reject", summary="[아니오]·[목록에 없음] → 다음 단계")
async def reject(payload: PillRejectRequest):
    return await _forward("/pill/reject", payload)


@router.post("/imprint-choice", summary="각인 화면 버튼(로고·각인 없음) → 색 선택")
async def imprint_choice(payload: PillImprintChoiceRequest):
    return await _forward("/pill/imprint-choice", payload)


@router.post("/refine", summary="각인 입력·색 선택으로 재검색")
async def refine(payload: PillRefineRequest):
    return await _forward("/pill/refine", payload)


@router.post("/confirm", summary="사용자가 고른 약 확정 → 챗봇 질문으로 넘길 값")
async def confirm(payload: PillConfirmRequest):
    return await _forward("/pill/confirm", payload)

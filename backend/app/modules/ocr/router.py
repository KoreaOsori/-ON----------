from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser
from app.core.config import settings
from app.integrations.bedrock import ClaudeUnavailableError
from app.modules.ocr import service
from app.modules.ocr.schemas import PrescriptionOcrRequest, PrescriptionOcrResponse

router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.post("/prescriptions", response_model=PrescriptionOcrResponse, summary="처방전·약봉투 인식")
async def recognize_prescription(payload: PrescriptionOcrRequest, user: CurrentUser):
    if f"/{user.id}/" not in payload.object_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "본인이 업로드한 파일만 인식할 수 있습니다.")
    try:
        candidates = await service.recognize_prescription(payload.object_key)
    except ClaudeUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "잠시 후 다시 시도해 주세요.") from error
    return PrescriptionOcrResponse(candidates=candidates, provider=settings.ocr_provider)

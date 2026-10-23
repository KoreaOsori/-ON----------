from fastapi import APIRouter, HTTPException, status

from app.api.deps import OptionalUser
from app.core.config import settings
from app.integrations.bedrock import ClaudeUnavailableError
from app.modules.ocr import service
from app.modules.ocr.schemas import (
    PrescriptionConfirmRequest,
    PrescriptionOcrRequest,
    PrescriptionOcrResponse,
)
from app.modules.pill import service as pill_worker

router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.post("/prescriptions", response_model=PrescriptionOcrResponse, summary="처방전·약봉투 인식")
async def recognize_prescription(payload: PrescriptionOcrRequest, user: OptionalUser):
    # 업로드(presign)와 같은 규칙: 회원은 본인 경로, 비회원(채팅 사진 첨부)은 guest 경로만
    owner = str(user.id) if user else "guest"
    if pill_worker.owner_of(payload.object_key) != owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "본인이 업로드한 파일만 인식할 수 있습니다.")
    if settings.ocr_provider == "worker":
        try:
            result = await service.recognize_with_worker(payload.object_key)
        except pill_worker.WorkerError as error:
            raise HTTPException(error.status, {"code": error.code, "message": error.message}) from error
        return PrescriptionOcrResponse(
            candidates=[service.to_candidate(drug) for drug in result.get("drugs", [])],
            provider="worker",
            notice=result.get("notice") or PrescriptionOcrResponse.model_fields["notice"].default,
            session_id=result.get("sessionId"),
            doc_type=result.get("docType"),
            drugs=result.get("drugs", []),
            json_ok=result.get("jsonOk"),
            privacy=result.get("privacy"),
            storage=result.get("storage"),
            timing_sec=result.get("timingSec"),
        )
    try:
        candidates = await service.recognize_prescription(payload.object_key)
    except ClaudeUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "잠시 후 다시 시도해 주세요.") from error
    return PrescriptionOcrResponse(candidates=candidates, provider=settings.ocr_provider)


@router.post("/prescriptions/confirm", summary="약 이름 확정 → 숫자 칸에 권장 용법 상한 검증 반영")
async def confirm_prescription_drug(payload: PrescriptionConfirmRequest):
    try:
        return await pill_worker.call("/rx/confirm", payload.model_dump(by_alias=True))
    except pill_worker.WorkerError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message}) from error

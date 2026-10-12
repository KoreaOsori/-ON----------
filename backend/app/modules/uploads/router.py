import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import OptionalUser
from app.core.config import settings
from app.integrations.aws import s3_presign_client
from app.modules.uploads.schemas import PresignRequest, PresignResponse

router = APIRouter(prefix="/uploads", tags=["uploads"])

EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


@router.post("/presign", response_model=PresignResponse, summary="S3 업로드용 presigned URL 발급")
async def presign_upload(payload: PresignRequest, user: OptionalUser):
    """브라우저가 S3 로 직접 PUT 업로드한다. 업로드 버킷은 수명주기 정책으로 일정 기간 후 자동 삭제된다."""
    owner = str(user.id) if user else "guest"
    object_key = f"{payload.purpose}/{datetime.now(UTC):%Y/%m/%d}/{owner}/{uuid.uuid4()}.{EXTENSIONS[payload.content_type]}"
    upload_url = s3_presign_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_upload_bucket, "Key": object_key, "ContentType": payload.content_type},
        ExpiresIn=settings.s3_presign_expires_seconds,
    )
    return PresignResponse(
        upload_url=upload_url,
        object_key=object_key,
        expires_in=settings.s3_presign_expires_seconds,
        max_bytes=settings.upload_max_bytes,
    )

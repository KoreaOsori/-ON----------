from typing import Literal

from app.core.schemas import CamelModel

# Claude 비전이 지원하는 형식만 허용 (HEIC 는 클라이언트에서 JPEG 로 변환)
AllowedContentType = Literal["image/jpeg", "image/png", "image/webp"]


class PresignRequest(CamelModel):
    content_type: AllowedContentType
    purpose: Literal["prescription", "pill"]


class PresignResponse(CamelModel):
    upload_url: str
    object_key: str
    expires_in: int
    max_bytes: int

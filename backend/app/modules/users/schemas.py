import uuid
from datetime import date
from typing import Literal

from pydantic import Field

from app.core.schemas import CamelModel

ConsentType = Literal["terms", "privacy", "health", "marketing"]
REQUIRED_CONSENTS: set[str] = {"terms", "privacy", "health"}


class UserRead(CamelModel):
    id: uuid.UUID
    email: str | None
    nickname: str | None
    provider: str


class ConsentUpdate(CamelModel):
    consents: dict[ConsentType, bool]


class MedicineItem(CamelModel):
    """건강정보에서 약 검색으로 고른 약 (병용 확인의 "내 복용약 불러오기"에 쓴다)"""

    id: str = Field(max_length=50)
    name: str = Field(max_length=200)
    maker: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=100)
    type: str = Field(default="", max_length=20)
    sale_status: str = Field(default="", max_length=20)
    image_url: str | None = Field(default=None, max_length=1000)


class HealthProfilePayload(CamelModel):
    birth: date
    gender: Literal["여성", "남성", "기타"]
    height: float = Field(ge=20, le=250)
    weight: float = Field(ge=1, le=400)
    pregnant: Literal["임신 중", "임신 아님", "확인 필요"]
    medicine_status: str
    medicines: list[str] = Field(default_factory=list, max_length=50)
    medicine_items: list[MedicineItem] = Field(default_factory=list, max_length=50)
    conditions: str = Field(min_length=1, max_length=1000)

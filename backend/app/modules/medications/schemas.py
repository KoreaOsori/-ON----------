import uuid
from datetime import date

from pydantic import Field

from app.core.schemas import CamelModel


class MedicationCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    item_seq: str | None = Field(default=None, pattern=r"^\d{1,20}$")
    amount: int | None = Field(default=None, ge=1, le=100)
    times_per_day: int | None = Field(default=None, ge=1, le=12)
    days: int | None = Field(default=None, ge=1, le=365)
    start_date: date | None = None


class MedicationUpdate(CamelModel):
    """복용 정보만 바꾼다 (이름을 바꾸려면 삭제 후 다시 등록). 보낸 값 그대로 덮어쓴다 (null = 모름)"""

    amount: int | None = Field(default=None, ge=1, le=100)
    times_per_day: int | None = Field(default=None, ge=1, le=12)
    days: int | None = Field(default=None, ge=1, le=365)
    start_date: date | None = None


class MedicationRead(MedicationCreate):
    id: uuid.UUID


class IntakeLogUpdate(CamelModel):
    date: date
    slot: str = Field(min_length=1, max_length=20)
    taken: bool


class IntakeLogRead(IntakeLogUpdate):
    medication_id: uuid.UUID

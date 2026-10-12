import uuid
from datetime import date

from pydantic import Field

from app.core.schemas import CamelModel


class MedicationCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    amount: int = Field(ge=1, le=100)
    times_per_day: int = Field(ge=1, le=12)
    days: int = Field(ge=1, le=365)
    start_date: date


class MedicationRead(MedicationCreate):
    id: uuid.UUID


class IntakeLogUpdate(CamelModel):
    date: date
    slot: str = Field(min_length=1, max_length=20)
    taken: bool


class IntakeLogRead(IntakeLogUpdate):
    medication_id: uuid.UUID

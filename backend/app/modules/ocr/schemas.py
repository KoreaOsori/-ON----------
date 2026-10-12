from pydantic import Field

from app.core.schemas import CamelModel


class PrescriptionOcrRequest(CamelModel):
    object_key: str = Field(pattern=r"^prescription/")


class MedicationCandidate(CamelModel):
    name: str
    amount: int | None = None
    times_per_day: int | None = None
    days: int | None = None


class PrescriptionOcrResponse(CamelModel):
    candidates: list[MedicationCandidate]
    provider: str
    notice: str = "자동 인식 결과는 틀릴 수 있어요. 저장 전에 반드시 직접 확인해 주세요."

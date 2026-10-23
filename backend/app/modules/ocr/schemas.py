from typing import Any

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
    """기존 필드(candidates·provider·notice)는 그대로 두고, 워커 결과 필드를 추가한다 (plan.md 4 (b)).

    candidates 의 숫자는 확신도가 높은 값(ui=미리 채움)만 채우고 나머지는 null — 낮은 값을 확정값처럼 보이지 않게.
    화면은 drugs[].fields.{dose,times,days}.{value,conf,ui} 와 drugs[].decision·candidates 를 쓰는 것을 권장.
    """

    candidates: list[MedicationCandidate]
    provider: str
    notice: str = "자동 인식 결과는 틀릴 수 있어요. 저장 전에 반드시 직접 확인해 주세요."
    # ↓ worker 일 때만 채워짐
    session_id: str | None = None
    doc_type: str | None = None
    drugs: list[dict[str, Any]] = []
    json_ok: bool | None = None
    privacy: dict[str, Any] | None = None
    storage: str | None = None
    timing_sec: dict[str, Any] | None = None


class PrescriptionConfirmRequest(CamelModel):
    session_id: str
    drug_index: int = Field(ge=0)
    item_seq: str

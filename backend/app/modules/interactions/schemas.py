from pydantic import Field

from app.core.schemas import CamelModel


class InteractionCheckRequest(CamelModel):
    medicine_ids: list[str] = Field(min_length=2, max_length=5)


class InteractionPair(CamelModel):
    first: str
    second: str
    contraindicated: bool
    dur_content: str | None = None
    easy_explanation: str | None = None


class InteractionCheckResponse(CamelModel):
    pairs: list[InteractionPair]
    notice: str = "3개 이상 동시 복용 시의 복합 상호작용은 확인할 수 없으며, 2개씩 비교한 결과만 제공합니다."

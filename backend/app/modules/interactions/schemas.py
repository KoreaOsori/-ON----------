from pydantic import Field

from app.core.schemas import CamelModel


class InteractionCheckRequest(CamelModel):
    medicine_ids: list[str] = Field(min_length=2, max_length=5)


class ContraindicationDetail(CamelModel):
    basis: str  # 품목 DUR (식약처 품목표) | 성분 규칙 (성분 기준으로 계산)
    first_ingredients: list[str]
    second_ingredients: list[str]
    content: str | None  # DUR 원문
    remark: str | None


class InteractionPair(CamelModel):
    first: str
    second: str
    contraindicated: bool
    level: str | None = None  # 금기 | 성분 기준 주의
    details: list[ContraindicationDetail] = []  # 같은 쌍의 근거 (성분 조합마다 1개) 모두
    discontinued: list[str] = []  # 이 쌍에 낀 판매중지 약 이름 (공식 DUR 판정 없음)
    easy_explanation: str | None = None


class InteractionCheckResponse(CamelModel):
    pairs: list[InteractionPair]
    notice: str = "3개 이상 동시 복용 시의 복합 상호작용은 확인할 수 없으며, 2개씩 비교한 결과만 제공합니다."

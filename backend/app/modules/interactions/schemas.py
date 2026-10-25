from pydantic import Field

from app.core.schemas import CamelModel
from app.modules.medicines.schemas import DurCaution


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


class DuplicateMedicine(CamelModel):
    name: str
    ingredients: list[str]  # 이 중복에 해당하는 이 약의 성분


class DuplicateCaution(CamelModel):
    """병용금기는 아니지만 겹쳐 먹으면 주의가 필요한 경우 (금지가 아니라 주의)"""

    kind: str  # 같은 성분 | 같은 계열 (식약처 DUR 효능군중복의 계열)
    name: str  # 성분 이름 또는 계열 이름
    medicines: list[DuplicateMedicine]
    daily_max: list[str]  # 해당 성분의 1일 최대 (식약처 DUR 용량주의, 단일 성분 기준). 없으면 비움


class MedicineCautions(CamelModel):
    """고른 약 하나의 DUR 주의 (임부·연령·노인 등). 사용자 프로필 없이 모두 보여준다"""

    name: str
    cautions: list[DurCaution]
    contraindicated_patients: list[str] = []  # 허가 문서 "투여하지 말 것" 항목 줄 (화면에서 지병과 맞춤)


class InteractionCheckResponse(CamelModel):
    pairs: list[InteractionPair]
    duplicates: list[DuplicateCaution] = []
    medicine_cautions: list[MedicineCautions] = []  # 고른 약 모두 (주의가 없으면 빈 목록)
    notice: str = "3개 이상 동시 복용 시의 복합 상호작용은 확인할 수 없으며, 2개씩 비교한 결과만 제공합니다."

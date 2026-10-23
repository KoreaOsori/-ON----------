from app.core.schemas import CamelModel


class HealthFoodSummary(CamelModel):
    id: str  # 품목제조번호
    name: str
    maker: str
    form: str  # 제형 원문 (정, 캡슐, 분말 …)


class HealthFoodDetail(HealthFoodSummary):
    functionality: str  # 주된 기능성
    intake_method: str  # 섭취 방법
    precautions: str  # 섭취 시 주의사항
    raw_materials: str  # 원재료
    storage: str  # 보관 방법
    shelf_life: str  # 유통기한
    permit_date: str | None  # 신고일 (YYYY-MM-DD)
    source: str = "식품의약품안전처 식품안전나라 건강기능식품 품목제조신고"

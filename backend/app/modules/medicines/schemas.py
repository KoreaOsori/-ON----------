from app.core.schemas import CamelModel


class MedicineSummary(CamelModel):
    id: str
    name: str
    maker: str
    category: str
    type: str  # 일반 | 전문
    sale_status: str = "판매"  # 판매 | 판매중지 (판매중지 약은 공식 DUR 판정 없음)


class MedicineDetail(MedicineSummary):
    efficacy: str
    usage: str
    precautions: str
    interaction_summary: str
    source: str


class ContraindicationRow(CamelModel):
    """병용금기 한 행. item_seq 약의 성분 × mixture_item_seq 약의 성분 조합마다 1행 (gold.drug_contraindication)"""

    item_seq: str
    mixture_item_seq: str
    basis: str  # 품목 DUR | 성분 규칙
    ingr_names: list[str]
    mixture_ingr_names: list[str]
    prohbt_content: str | None
    remark: str | None


class IngredientRow(CamelModel):
    """약 하나의 성분 하나 (gold.drug_ingredient) + 그 성분의 효능군·1일 최대 용량 (gold.dur_ingredient_rule)"""

    item_seq: str
    ingr_key: str  # DUR 성분 코드(D코드), 없으면 성분 이름
    ingr_name: str
    efficacy_group: str | None  # 효능군중복의 계열 (예: 비스테로이드성 소염제)
    daily_max: list[str]  # 용량주의 1일 최대 (단일 성분 기준, 값이 여럿이면 모두)

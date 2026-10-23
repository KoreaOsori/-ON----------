from app.core.schemas import CamelModel


class MedicineSummary(CamelModel):
    id: str
    name: str
    maker: str
    category: str
    type: str  # 일반 | 전문
    sale_status: str = "판매"  # 판매 | 판매중지 (판매중지 약은 공식 DUR 판정 없음)
    image_url: str | None = None  # 식약처 의약품안전나라 제품 사진 주소 (gold.drug.image_url, 없는 약이 많음)


class DurCaution(CamelModel):
    """약 하나의 식약처 DUR 주의 한 건 (gold.drug_dur_caution)"""

    type: str  # 임부금기 | 특정연령대금기 | 노인주의 | 투여기간주의 | 서방정분할주의
    ingredient: str | None
    grade: str | None  # 임부금기 등급 (1등급 / 2등급)
    age_base: str | None  # 특정연령대금기 기준 (예: 12세 미만)
    max_dosage_term: str | None  # 투여기간주의 최대 투여기간
    content: str | None  # 금기·주의 내용 (노인주의는 대부분 없음)
    remark: str | None


class MedicineDetail(MedicineSummary):
    efficacy: str
    usage: str
    precautions: str
    interaction_summary: str
    source: str
    dur_cautions: list[DurCaution] = []  # 비어 있으면 "등록된 DUR 주의 없음" (안전하다는 뜻이 아님)


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

"""건강기능식품 조회. 데이터 파이프라인이 RDS 에 적재한 gold.health_food (식품안전나라 C003) 기준.

판매 여부 필드가 없어 2004년 신고분부터 모두 들어 있다. DRUG_DATA_SOURCE 가 gold 가 아니면 (목업·로컬) 빈 결과.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.health_foods.schemas import HealthFoodDetail, HealthFoodSummary

SEARCH_LIMIT = 50
# 제형 분류 (화면 버튼) → 원본 제형 값. 어디에도 없는 제형은 "기타"
FORMS: dict[str, tuple[str, ...]] = {
    "정": ("정",),
    "캡슐": ("캡슐",),
    "분말·과립": ("분말", "과립"),
    "액상·시럽": ("액상", "시럽"),
    "젤리·겔": ("젤리", "겔", "페이스트상"),
    "환": ("환",),
}
OTHER = "기타"
_SUMMARY_COLUMNS = "prdlst_report_no, prdlst_nm, bssh_nm, prdt_shap_cd_nm"


def form_names() -> list[str]:
    return [*FORMS, OTHER]


def _summary(row) -> dict:
    return {
        "id": row.prdlst_report_no,
        "name": row.prdlst_nm,
        "maker": row.bssh_nm or "",
        "form": row.prdt_shap_cd_nm or "",
    }


async def search(session: AsyncSession, query: str, form: str | None) -> list[HealthFoodSummary]:
    if settings.drug_data_source != "gold":
        return []
    if not query and form not in (*FORMS, OTHER):  # 검색어도 제형도 없으면 4만 개 전체를 내려보내지 않는다
        return []
    conditions = []
    params: dict = {"limit": SEARCH_LIMIT}
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("prdlst_nm ILIKE :pattern")
        params["pattern"] = f"%{escaped}%"
    if form in FORMS:
        conditions.append("prdt_shap_cd_nm = ANY(:forms)")
        params["forms"] = list(FORMS[form])
    elif form == OTHER:
        conditions.append("(prdt_shap_cd_nm IS NULL OR NOT prdt_shap_cd_nm = ANY(:forms))")
        params["forms"] = [value for values in FORMS.values() for value in values]
    result = await session.execute(
        text(
            f"SELECT {_SUMMARY_COLUMNS} FROM gold.health_food WHERE {' AND '.join(conditions)} "
            "ORDER BY length(prdlst_nm), prdlst_nm LIMIT :limit"
        ),
        params,
    )
    return [HealthFoodSummary(**_summary(row)) for row in result]


async def get(session: AsyncSession, health_food_id: str) -> HealthFoodDetail | None:
    if settings.drug_data_source != "gold":
        return None
    result = await session.execute(
        text(
            f"SELECT {_SUMMARY_COLUMNS}, primary_fnclty, ntk_mthd, iftkn_atnt_matr_cn, rawmtrl_nm, cstdy_mthd, "
            "pog_daycnt, permit_date FROM gold.health_food WHERE prdlst_report_no = :id"
        ),
        {"id": health_food_id},
    )
    row = result.first()
    if row is None:
        return None
    return HealthFoodDetail(
        **_summary(row),
        functionality=row.primary_fnclty or "",
        intake_method=row.ntk_mthd or "",
        precautions=row.iftkn_atnt_matr_cn or "",
        raw_materials=row.rawmtrl_nm or "",
        storage=row.cstdy_mthd or "",
        shelf_life=row.pog_daycnt or "",
        permit_date=row.permit_date.isoformat() if row.permit_date else None,
    )

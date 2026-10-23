"""의약품 조회 서비스. DRUG_DATA_SOURCE 설정으로 목업 / 공공데이터 API / gold(RDS) 를 전환한다."""

import re
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.integrations import public_data
from app.modules.medicines.categories import class_code_patterns
from app.modules.medicines.mock_data import MOCK_CONTRAINDICATED_PAIRS, MOCK_MEDICINES
from app.modules.medicines.schemas import (
    ContraindicationRow,
    DurCaution,
    IngredientRow,
    MedicineDetail,
    MedicineSummary,
)

SEARCH_LIMIT = 50
_SECTION_TITLE = re.compile(r"^\d+\.\s")  # 허가 문서 큰 항목 제목 (예: "3. 다음 환자에는 신중히 투여할 것.")


def contraindicated_patients(precautions: str | None) -> list[str]:
    """허가 문서 사용상의 주의사항 중 "다음 환자에는 투여하지 말 것" 항목의 줄들 (예: "6) 심한 고혈압 환자").
    지병과 맞추는 일은 화면(브라우저)에서 한다 — 건강정보를 서버로 보내지 않기 위해"""
    lines = (precautions or "").split("\n")
    start = next((i for i, line in enumerate(lines) if "투여하지 말 것" in line and _SECTION_TITLE.match(line)), None)
    if start is None:
        return []
    section = []
    for line in lines[start + 1 :]:
        if _SECTION_TITLE.match(line):
            break
        if line.strip():
            section.append(line.strip())
    return section
# 약 상세에 보여주는 DUR 주의 (이 순서로)
DUR_CAUTION_TYPES = ("임부금기", "특정연령대금기", "노인주의", "투여기간주의", "서방정분할주의")


class MedicineRepository(Protocol):
    async def search(
        self, query: str, category: str | None, medicine_type: str | None
    ) -> list[MedicineSummary]: ...
    async def get(self, medicine_id: str) -> MedicineDetail | None: ...
    async def find_in_text(self, text: str) -> MedicineDetail | None: ...
    async def contraindications(self, medicine_ids: list[str]) -> list[ContraindicationRow]: ...
    async def ingredients(self, medicine_ids: list[str]) -> list[IngredientRow]: ...


class MockMedicineRepository:
    async def search(
        self, query: str, category: str | None, medicine_type: str | None
    ) -> list[MedicineSummary]:
        return [
            MedicineSummary.model_validate(item.model_dump())
            for item in MOCK_MEDICINES
            if query in item.name
            and (not category or category == "전체" or item.category == category)
            and (not medicine_type or item.type == medicine_type)
        ]

    async def get(self, medicine_id: str) -> MedicineDetail | None:
        return next((item for item in MOCK_MEDICINES if item.id == medicine_id), None)

    async def find_in_text(self, text: str) -> MedicineDetail | None:
        return next((item for item in MOCK_MEDICINES if item.name in text), None)

    async def contraindications(self, medicine_ids: list[str]) -> list[ContraindicationRow]:
        rows = []
        for pair in MOCK_CONTRAINDICATED_PAIRS:
            if pair <= set(medicine_ids):
                first, second = sorted(pair)
                for item_seq, mixture_item_seq in ((first, second), (second, first)):
                    rows.append(
                        ContraindicationRow(
                            item_seq=item_seq,
                            mixture_item_seq=mixture_item_seq,
                            basis="품목 DUR",
                            ingr_names=["가상 성분"],
                            mixture_ingr_names=["가상 성분"],
                            prohbt_content="가상의 성분 간 병용 제한 내용입니다. 실제 DUR 데이터가 아닙니다.",
                            remark=None,
                        )
                    )
        return rows

    async def ingredients(self, medicine_ids: list[str]) -> list[IngredientRow]:
        return []  # 가상 약에는 성분 정보가 없다


class PublicApiMedicineRepository:
    """식약처 e약은요 API. 분류(category)·전문/일반 구분은 별도 데이터 매핑이 필요하다."""

    @staticmethod
    def _to_detail(item: dict) -> MedicineDetail:
        return MedicineDetail(
            id=str(item.get("itemSeq", "")),
            name=item.get("itemName", ""),
            maker=item.get("entpName", ""),
            category="",
            type="",
            efficacy=item.get("efcyQesitm") or "",
            usage=item.get("useMethodQesitm") or "",
            precautions="\n".join(filter(None, [item.get("atpnWarnQesitm"), item.get("atpnQesitm")])),
            interaction_summary=item.get("intrcQesitm") or "",
            source="식품의약품안전처 의약품개요정보(e약은요)",
        )

    async def search(
        self, query: str, category: str | None, medicine_type: str | None
    ) -> list[MedicineSummary]:
        items = await public_data.fetch_easy_drug_list(item_name=query)
        return [MedicineSummary.model_validate(self._to_detail(item).model_dump()) for item in items]

    async def get(self, medicine_id: str) -> MedicineDetail | None:
        items = await public_data.fetch_easy_drug_list(item_seq=medicine_id, rows=1)
        return self._to_detail(items[0]) if items else None

    async def find_in_text(self, text: str) -> MedicineDetail | None:
        # TODO: 질문에서 약 이름을 추출하는 로직(사전 매칭 / LLM 추출) 필요
        return None

    async def contraindications(self, medicine_ids: list[str]) -> list[ContraindicationRow]:
        raise NotImplementedError(
            "공공데이터 API 모드는 병용금기(DUR)를 연동하지 않았습니다. DRUG_DATA_SOURCE=gold 를 사용하세요."
        )

    async def ingredients(self, medicine_ids: list[str]) -> list[IngredientRow]:
        raise NotImplementedError(
            "공공데이터 API 모드는 성분(DUR)을 연동하지 않았습니다. DRUG_DATA_SOURCE=gold 를 사용하세요."
        )


class GoldMedicineRepository:
    """데이터 파이프라인이 RDS 에 적재한 gold 스키마 (gold.drug, gold.drug_contraindication)"""

    _SUMMARY_COLUMNS = "item_seq, item_name, entp_name, class_name, etc_otc_name, sale_status, image_url"

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _summary_fields(row) -> dict:
        return {
            "id": row.item_seq,
            "name": row.item_name,
            "maker": row.entp_name or "",
            "category": row.class_name or "",
            "type": (row.etc_otc_name or "").removesuffix("의약품"),  # 일반의약품 → 일반
            "sale_status": row.sale_status,
            "image_url": row.image_url,
        }

    async def search(
        self, query: str, category: str | None, medicine_type: str | None
    ) -> list[MedicineSummary]:
        # 하위 분류(일반·전문 안의 대표 분류)는 약효분류 코드 묶음으로 거른다 (categories.py)
        patterns = class_code_patterns(medicine_type, category) if medicine_type and category else None
        if not query and patterns is None:  # 검색어도 분류도 없으면 약 4만 개 전체를 내려보내지 않는다
            return []
        conditions = []
        params: dict = {"limit": SEARCH_LIMIT}
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("item_name ILIKE :pattern")
            params["pattern"] = f"%{escaped}%"
        if patterns is not None:
            codes, other = patterns
            conditions.append(
                "(class_code IS NULL OR NOT class_code LIKE ANY(:codes))"
                if other
                else "class_code LIKE ANY(:codes)"
            )
            params["codes"] = codes
        if medicine_type:
            conditions.append("etc_otc_name = :etc_otc_name")
            params["etc_otc_name"] = f"{medicine_type}의약품"
        # 판매 중 → 사진 있는 약 → 이름이 짧은 순 (사진은 알약에만 있어 물약·주사·외용제는 뒤로 간다)
        result = await self.session.execute(
            text(
                f"SELECT {self._SUMMARY_COLUMNS} FROM gold.drug WHERE {' AND '.join(conditions)} "
                "ORDER BY sale_status = '판매중지', image_url IS NULL, length(item_name), item_name LIMIT :limit"
            ),
            params,
        )
        return [MedicineSummary(**self._summary_fields(row)) for row in result]

    async def get(self, medicine_id: str) -> MedicineDetail | None:
        result = await self.session.execute(
            text(
                f"SELECT {self._SUMMARY_COLUMNS}, easy_efcy, easy_use_method, easy_atpn_warn, easy_atpn, easy_intrc, "
                "doc_efficacy, doc_dosage, doc_precautions FROM gold.drug WHERE item_seq = :item_seq"
            ),
            {"item_seq": medicine_id},
        )
        row = result.first()
        if row is None:
            return None
        # 약 하나에 해당하는 DUR 주의. 용량주의·효능군중복은 병용 확인의 "중복 주의"에서 보여준다.
        # 품목 규칙의 내용·비고가 없으면 연결된 성분 규칙의 것을 쓴다
        cautions = await self.session.execute(
            text(
                "SELECT DISTINCT caution_type, ingr_name, grade, age_base, max_dosage_term, "
                "coalesce(prohbt_content, rule_prohbt_content) AS content, coalesce(remark, rule_remark) AS remark, "
                "array_position(CAST(:types AS text[]), caution_type) AS type_order "
                "FROM gold.drug_dur_caution WHERE item_seq = :item_seq AND caution_type = ANY(:types) "
                "ORDER BY type_order, ingr_name, grade"
            ),
            {"item_seq": medicine_id, "types": list(DUR_CAUTION_TYPES)},
        )
        # 일반인용 e약은요가 있으면 그것을, 없으면 허가 문서(전문가용 원문)를 보여준다
        easy_precautions = "\n".join(filter(None, [row.easy_atpn_warn, row.easy_atpn]))
        return MedicineDetail(
            **self._summary_fields(row),
            efficacy=row.easy_efcy or row.doc_efficacy or "",
            usage=row.easy_use_method or row.doc_dosage or "",
            precautions=easy_precautions or row.doc_precautions or "",
            interaction_summary=row.easy_intrc or "",
            source="식품의약품안전처 의약품개요정보(e약은요)"
            if row.easy_efcy
            else "식품의약품안전처 의약품 제품 허가정보",
            dur_cautions=[
                DurCaution(
                    type=c.caution_type,
                    ingredient=c.ingr_name,
                    grade=c.grade,
                    age_base=c.age_base,
                    max_dosage_term=c.max_dosage_term,
                    content=c.content,
                    remark=c.remark,
                )
                for c in cautions
            ],
            contraindicated_patients=contraindicated_patients(row.doc_precautions),
        )

    async def find_in_text(self, text: str) -> MedicineDetail | None:
        # TODO: 질문에서 약 이름을 추출하는 로직(사전 매칭 / LLM 추출) 필요
        return None

    async def contraindications(self, medicine_ids: list[str]) -> list[ContraindicationRow]:
        # 양방향으로 들어 있으므로 (A, B), (B, A) 모두 나온다
        result = await self.session.execute(
            text(
                "SELECT item_seq, mixture_item_seq, basis, ingr_names, mixture_ingr_names, prohbt_content, remark "
                "FROM gold.drug_contraindication "
                "WHERE item_seq = ANY(:ids) AND mixture_item_seq = ANY(:ids) ORDER BY basis = '성분 규칙', id"
            ),
            {"ids": medicine_ids},
        )
        return [
            ContraindicationRow(
                item_seq=row.item_seq,
                mixture_item_seq=row.mixture_item_seq,
                basis=row.basis,
                ingr_names=row.ingr_names or [],
                mixture_ingr_names=row.mixture_ingr_names or [],
                prohbt_content=row.prohbt_content,
                remark=row.remark,
            )
            for row in result
        ]

    async def ingredients(self, medicine_ids: list[str]) -> list[IngredientRow]:
        # 먹는 약만 비교한다: 경구 외(파스·안약·주사 등) 제품은 빼고, 경로를 모르는 제품(null)은 넣는다.
        # 성분 규칙(gold.dur_ingredient_rule)의 단일 성분 규칙만 쓴다. 복합 규칙은 특정 복합제 조합에만 해당한다.
        # 1일 최대도 경구 외 제형에만 정해진 규칙(주사 등)은 뺀다
        result = await self.session.execute(
            text(
                "WITH ingredient AS (SELECT i.item_seq, i.ingr_key, i.ingr_name, i.dur_ingr_code "
                "FROM gold.drug_ingredient i JOIN gold.drug d USING (item_seq) "
                "WHERE i.item_seq = ANY(:ids) AND d.route IS DISTINCT FROM '경구 외'), "
                "rule AS (SELECT * FROM gold.dur_ingredient_rule WHERE mix_type = '단일' "
                "AND ingr_code IN (SELECT dur_ingr_code FROM ingredient)), "
                "efficacy AS (SELECT ingr_code, min(sers_name) AS sers_name FROM rule "
                "WHERE caution_type = '효능군중복' GROUP BY ingr_code), "
                "dose AS (SELECT ingr_code, array_agg(max_qty ORDER BY source_key) AS max_qty, "
                "array_agg(coalesce(form_name, '') ORDER BY source_key) AS form_name FROM rule "
                "WHERE caution_type = '용량주의' AND max_qty IS NOT NULL AND route IS DISTINCT FROM '경구 외' "
                "GROUP BY ingr_code) "
                "SELECT i.item_seq, i.ingr_key, i.ingr_name, e.sers_name, d.max_qty, d.form_name FROM ingredient i "
                "LEFT JOIN efficacy e ON e.ingr_code = i.dur_ingr_code LEFT JOIN dose d ON d.ingr_code = i.dur_ingr_code "
                "ORDER BY i.item_seq, i.ingr_name"
            ),
            {"ids": medicine_ids},
        )
        return [
            IngredientRow(
                item_seq=row.item_seq,
                ingr_key=row.ingr_key,
                ingr_name=row.ingr_name,
                efficacy_group=row.sers_name,
                # "600밀리그램" 처럼 숫자만 있으면 성분 이름을 붙이고, 제형이 정해진 규칙은 제형을 붙인다
                daily_max=[
                    (f"{row.ingr_name} {qty}" if qty[0].isdigit() else qty) + (f" ({form})" if form else "")
                    for qty, form in zip(row.max_qty or [], row.form_name or [], strict=True)
                ],
            )
            for row in result
        ]


def get_medicine_repository(session: Annotated[AsyncSession, Depends(get_db)]) -> MedicineRepository:
    if settings.drug_data_source == "gold":
        return GoldMedicineRepository(session)
    if settings.drug_data_source == "public_api":
        return PublicApiMedicineRepository()
    return MockMedicineRepository()

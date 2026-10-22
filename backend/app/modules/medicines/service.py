"""의약품 조회 서비스. DRUG_DATA_SOURCE 설정으로 목업 / 공공데이터 API / gold(RDS) 를 전환한다."""

from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.integrations import public_data
from app.modules.medicines.mock_data import MOCK_CONTRAINDICATED_PAIRS, MOCK_MEDICINES
from app.modules.medicines.schemas import ContraindicationRow, MedicineDetail, MedicineSummary

SEARCH_LIMIT = 50


class MedicineRepository(Protocol):
    async def search(
        self, query: str, category: str | None, medicine_type: str | None
    ) -> list[MedicineSummary]: ...
    async def get(self, medicine_id: str) -> MedicineDetail | None: ...
    async def find_in_text(self, text: str) -> MedicineDetail | None: ...
    async def contraindications(self, medicine_ids: list[str]) -> list[ContraindicationRow]: ...


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


class GoldMedicineRepository:
    """데이터 파이프라인이 RDS 에 적재한 gold 스키마 (gold.drug, gold.drug_contraindication)"""

    _SUMMARY_COLUMNS = "item_seq, item_name, entp_name, class_name, etc_otc_name, sale_status"

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
        }

    async def search(
        self, query: str, category: str | None, medicine_type: str | None
    ) -> list[MedicineSummary]:
        if not query:  # 약 4만 개 전체를 내려보내지 않는다
            return []
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions = ["item_name ILIKE :pattern"]
        params: dict = {"pattern": f"%{escaped}%", "limit": SEARCH_LIMIT}
        if category and category != "전체":
            conditions.append("class_name = :category")
            params["category"] = category
        if medicine_type:
            conditions.append("etc_otc_name = :etc_otc_name")
            params["etc_otc_name"] = f"{medicine_type}의약품"
        result = await self.session.execute(
            text(
                f"SELECT {self._SUMMARY_COLUMNS} FROM gold.drug WHERE {' AND '.join(conditions)} "
                "ORDER BY sale_status = '판매중지', length(item_name), item_name LIMIT :limit"
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


def get_medicine_repository(session: Annotated[AsyncSession, Depends(get_db)]) -> MedicineRepository:
    if settings.drug_data_source == "gold":
        return GoldMedicineRepository(session)
    if settings.drug_data_source == "public_api":
        return PublicApiMedicineRepository()
    return MockMedicineRepository()

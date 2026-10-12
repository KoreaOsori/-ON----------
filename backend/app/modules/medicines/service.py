"""의약품 조회 서비스. DRUG_DATA_SOURCE 설정으로 목업 / 공공데이터 API 를 전환한다."""

from typing import Protocol

from app.core.config import settings
from app.integrations import public_data
from app.modules.medicines.mock_data import MOCK_MEDICINES
from app.modules.medicines.schemas import MedicineDetail, MedicineSummary


class MedicineRepository(Protocol):
    async def search(self, query: str, category: str | None) -> list[MedicineSummary]: ...
    async def get(self, medicine_id: str) -> MedicineDetail | None: ...
    async def find_in_text(self, text: str) -> MedicineDetail | None: ...


class MockMedicineRepository:
    async def search(self, query: str, category: str | None) -> list[MedicineSummary]:
        return [
            MedicineSummary.model_validate(item.model_dump())
            for item in MOCK_MEDICINES
            if query in item.name and (not category or category == "전체" or item.category == category)
        ]

    async def get(self, medicine_id: str) -> MedicineDetail | None:
        return next((item for item in MOCK_MEDICINES if item.id == medicine_id), None)

    async def find_in_text(self, text: str) -> MedicineDetail | None:
        return next((item for item in MOCK_MEDICINES if item.name in text), None)


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

    async def search(self, query: str, category: str | None) -> list[MedicineSummary]:
        items = await public_data.fetch_easy_drug_list(item_name=query)
        return [MedicineSummary.model_validate(self._to_detail(item).model_dump()) for item in items]

    async def get(self, medicine_id: str) -> MedicineDetail | None:
        items = await public_data.fetch_easy_drug_list(item_seq=medicine_id, rows=1)
        return self._to_detail(items[0]) if items else None

    async def find_in_text(self, text: str) -> MedicineDetail | None:
        # TODO: 질문에서 약 이름을 추출하는 로직(사전 매칭 / LLM 추출) 필요
        return None


def get_medicine_repository() -> MedicineRepository:
    if settings.drug_data_source == "public_api":
        return PublicApiMedicineRepository()
    return MockMedicineRepository()

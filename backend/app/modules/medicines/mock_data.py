"""프론트엔드 목업과 동일한 가상 의약품 데이터 (실제 의료 정보 아님)"""

from app.modules.medicines.schemas import MedicineDetail

_PLACEHOLDER = "화면 구성을 위한 예시 정보입니다. 실제 복용 안내는 약사·의사와 상담해 주세요."
_SOURCE = "가상 데이터 (식약처 e약은요 형식 예시)"


def _drug(id_: str, name: str, maker: str, category: str, type_: str) -> MedicineDetail:
    return MedicineDetail(
        id=id_,
        name=name,
        maker=maker,
        category=category,
        type=type_,
        efficacy=_PLACEHOLDER,
        usage=_PLACEHOLDER,
        precautions=_PLACEHOLDER,
        interaction_summary=_PLACEHOLDER,
        source=_SOURCE,
    )


MOCK_MEDICINES: list[MedicineDetail] = [
    _drug("mock-0", "가나다정", "가상제약", "해열진통제", "일반"),
    _drug("mock-1", "라마바정", "온유제약 (가상)", "감기약", "일반"),
    _drug("mock-2", "사아자정", "가상바이오", "소화제", "전문"),
    _drug("mock-3", "차카타정", "가상제약", "알레르기약", "전문"),
    _drug("mock-4", "마바사정", "온유제약 (가상)", "피부약", "일반"),
]

# 데모용 병용금기 조합 (가나다정 + 마바사정)
MOCK_CONTRAINDICATED_PAIRS: set[frozenset[str]] = {frozenset({"mock-0", "mock-4"})}

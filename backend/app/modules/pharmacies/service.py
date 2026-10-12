"""주변 약국 조회. 현재는 목업이며 아래 연동을 예정한다.

TODO
- 국립중앙의료원 약국 위치정보 API(getParmacyLcinfoInqire)로 좌표 기반 조회
- 주소 검색은 지오코딩(카카오/네이버 로컬 API)으로 좌표 변환 후 동일 로직 사용
- 영업 여부는 요일별 영업시간(dutyTime1s~8c)으로 계산 (KST 기준)
"""

from app.modules.pharmacies.schemas import PharmacyRead

MOCK_PHARMACIES = [
    PharmacyRead(
        id="mock-1",
        name="온마음약국",
        address="가상시 온유로 24",
        phone=None,
        distance_meters=250,
        latitude=37.5665,
        longitude=126.9780,
        is_open=True,
        status_text="영업 중 · 22:00까지",
    ),
    PharmacyRead(
        id="mock-2",
        name="푸른약국",
        address="가상시 온유로 68",
        phone=None,
        distance_meters=480,
        latitude=37.5671,
        longitude=126.9795,
        is_open=False,
        status_text="영업 종료",
    ),
    PharmacyRead(
        id="mock-3",
        name="하루약국",
        address="가상시 안심길 12",
        phone=None,
        distance_meters=720,
        latitude=37.5650,
        longitude=126.9762,
        is_open=False,
        status_text="오늘 휴무",
    ),
]


async def find_pharmacies(
    *, lat: float | None, lng: float | None, address: str | None, open_only: bool
) -> list[PharmacyRead]:
    results = sorted(MOCK_PHARMACIES, key=lambda pharmacy: pharmacy.distance_meters)
    return [pharmacy for pharmacy in results if pharmacy.is_open or not open_only]

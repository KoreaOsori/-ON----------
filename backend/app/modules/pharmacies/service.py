"""주변 약국 조회. 국립중앙의료원 약국 정보 API(공공데이터포털)를 사용한다.

- 목록: 좌표 기반 거리순 + 오늘 영업시간(startTime/endTime)으로 영업 여부를 KST 기준 계산
- 상세: 요일별 영업시간(dutyTime1~8, 월~일·공휴일)
- 공휴일 여부는 알 수 없어 요일 기준으로만 판단한다. 화면에서 방문 전 전화 확인을 안내한다.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from app.integrations import public_data
from app.modules.pharmacies.schemas import PharmacyDetail, PharmacyHours, PharmacyRead

KST = timezone(timedelta(hours=9))  # 서머타임 없음. 슬림 이미지에 tzdata 가 없어도 동작
DAYS = ["월", "화", "수", "목", "금", "토", "일", "공휴일"]


def _minutes(value: Any) -> int | None:
    """HHMM (문자열 "0900" 또는 숫자 900, 자정을 넘기면 2600 처럼 올 수 있음) → 분"""
    if value in (None, ""):
        return None
    text = str(value).strip().zfill(4)
    if not text.isdigit():
        return None
    return int(text[:-2]) * 60 + int(text[-2:])


def _clock(minutes: int) -> str:
    hours, rest = divmod(minutes % (24 * 60), 60)
    return f"{hours:02d}:{rest:02d}"


def _closing_clock(minutes: int) -> str:
    """마감 시각은 자정을 00:00 이 아니라 24:00 으로 표시"""
    return "24:00" if minutes % (24 * 60) == 0 else _clock(minutes)


def _hours_text(start: Any, end: Any) -> str | None:
    opens, closes = _minutes(start), _minutes(end)
    if opens is None or closes is None:
        return None
    if closes <= opens:  # 자정을 넘겨 영업
        closes += 24 * 60
    if closes - opens >= 24 * 60:
        return "24시간"
    return f"{_clock(opens)}~{_closing_clock(closes)}"


def open_status(start: Any, end: Any, now: datetime) -> tuple[bool, str]:
    opens, closes = _minutes(start), _minutes(end)
    if opens is None or closes is None:
        return False, "영업시간 정보 없음"
    if closes <= opens:  # 자정을 넘겨 영업
        closes += 24 * 60
    current = now.hour * 60 + now.minute
    if opens <= current < closes or current + 24 * 60 < closes:
        return True, f"영업 중 · {_closing_clock(closes)}까지"
    if current < opens:
        return False, f"영업 전 · {_clock(opens)} 시작"
    return False, "영업 종료"


def _phone(item: dict[str, Any]) -> str | None:
    return (item.get("dutyTel1") or "").strip() or None


async def find_pharmacies(*, lat: float, lng: float, open_only: bool) -> list[PharmacyRead]:
    now = datetime.now(KST)
    pharmacies = []
    for item in await public_data.fetch_pharmacies_near(lat=lat, lng=lng):
        is_open, status_text = open_status(item.get("startTime"), item.get("endTime"), now)
        if open_only and not is_open:
            continue
        pharmacies.append(
            PharmacyRead(
                id=item["hpid"],
                name=item["dutyName"],
                address=item.get("dutyAddr", ""),
                phone=_phone(item),
                distance_meters=round(float(item.get("distance", 0)) * 1000),
                latitude=float(item["latitude"]),
                longitude=float(item["longitude"]),
                is_open=is_open,
                status_text=status_text,
                today_hours=_hours_text(item.get("startTime"), item.get("endTime")),
            )
        )
    return sorted(pharmacies, key=lambda pharmacy: pharmacy.distance_meters)


async def get_pharmacy(pharmacy_id: str) -> PharmacyDetail | None:
    item = await public_data.fetch_pharmacy_detail(pharmacy_id)
    if not item:
        return None
    lat, lng = item.get("wgs84Lat"), item.get("wgs84Lon")
    return PharmacyDetail(
        id=item["hpid"],
        name=item["dutyName"],
        address=item.get("dutyAddr", ""),
        phone=_phone(item),
        latitude=float(lat) if lat else None,
        longitude=float(lng) if lng else None,
        hours=[
            PharmacyHours(
                day=day,
                hours=_hours_text(item.get(f"dutyTime{order}s"), item.get(f"dutyTime{order}c")),
            )
            for order, day in enumerate(DAYS, start=1)
        ],
        note=item.get("dutyEtc"),
        directions=item.get("dutyMapimg"),
    )

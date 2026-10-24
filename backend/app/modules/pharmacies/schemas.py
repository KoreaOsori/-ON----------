from app.core.schemas import CamelModel


class PharmacyRead(CamelModel):
    id: str
    name: str
    address: str
    phone: str | None
    distance_meters: int
    latitude: float
    longitude: float
    is_open: bool
    status_text: str
    today_hours: str | None


class PharmacyHours(CamelModel):
    day: str
    hours: str | None  # None = 휴무 또는 정보 없음


class PharmacyDetail(CamelModel):
    id: str
    name: str
    address: str
    phone: str | None
    latitude: float | None
    longitude: float | None
    hours: list[PharmacyHours]
    note: str | None  # 휴게시간 등 비고
    directions: str | None  # 찾아오는 길

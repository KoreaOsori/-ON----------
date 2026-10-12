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

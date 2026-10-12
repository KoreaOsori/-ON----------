from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.modules.pharmacies import service
from app.modules.pharmacies.schemas import PharmacyRead

router = APIRouter(prefix="/pharmacies", tags=["pharmacies"])


@router.get("", response_model=list[PharmacyRead], summary="주변 약국 (좌표 또는 주소)")
async def find_pharmacies(
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    address: Annotated[str | None, Query(max_length=200)] = None,
    open_only: Annotated[bool, Query(alias="openOnly")] = False,
):
    if (lat is None or lng is None) and not address:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "좌표(lat, lng) 또는 주소가 필요합니다.")
    return await service.find_pharmacies(lat=lat, lng=lng, address=address, open_only=open_only)

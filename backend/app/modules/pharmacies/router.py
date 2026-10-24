from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.integrations.public_data import PublicDataError
from app.modules.pharmacies import service
from app.modules.pharmacies.schemas import PharmacyDetail, PharmacyRead

router = APIRouter(prefix="/pharmacies", tags=["pharmacies"])


@router.get("", response_model=list[PharmacyRead], summary="주변 약국 (좌표 기준 거리순)")
async def find_pharmacies(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    open_only: Annotated[bool, Query(alias="openOnly")] = False,
):
    try:
        return await service.find_pharmacies(lat=lat, lng=lng, open_only=open_only)
    except PublicDataError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "약국 정보를 불러오지 못했습니다.") from error


@router.get("/{pharmacy_id}", response_model=PharmacyDetail, summary="약국 상세 (요일별 영업시간)")
async def get_pharmacy(pharmacy_id: Annotated[str, Path(pattern=r"^[A-Z0-9]{1,20}$")]):
    try:
        pharmacy = await service.get_pharmacy(pharmacy_id)
    except PublicDataError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "약국 정보를 불러오지 못했습니다.") from error
    if not pharmacy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "약국을 찾을 수 없습니다.")
    return pharmacy

from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.interactions import service
from app.modules.interactions.schemas import InteractionCheckRequest, InteractionCheckResponse
from app.modules.medicines.service import MedicineRepository, get_medicine_repository

router = APIRouter(prefix="/interactions", tags=["interactions"])


@router.post("/check", response_model=InteractionCheckResponse, summary="병용금기 확인 (최대 5개)")
async def check_interactions(
    payload: InteractionCheckRequest,
    repository: Annotated[MedicineRepository, Depends(get_medicine_repository)],
):
    pairs = await service.check_pairs(repository, payload.medicine_ids)
    return InteractionCheckResponse(pairs=pairs)

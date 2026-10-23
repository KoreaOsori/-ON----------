from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.modules.medicines.categories import category_names
from app.modules.medicines.schemas import MedicineDetail, MedicineSummary
from app.modules.medicines.service import MedicineRepository, get_medicine_repository

router = APIRouter(prefix="/medicines", tags=["medicines"])

Repository = Annotated[MedicineRepository, Depends(get_medicine_repository)]


@router.get("", response_model=list[MedicineSummary], summary="약 검색")
async def search_medicines(
    repository: Repository,
    q: Annotated[str, Query(max_length=100)] = "",
    category: Annotated[
        str | None, Query(description="하위 분류 (GET /medicines/categories, type 과 함께)")
    ] = None,
    medicine_type: Annotated[Literal["일반", "전문"] | None, Query(alias="type")] = None,
):
    return await repository.search(q.strip(), category, medicine_type)


@router.get("/categories", summary="약 검색 하위 분류 (일반·전문별)")
async def list_categories() -> dict[str, list[str]]:
    return category_names()


@router.get("/{medicine_id}", response_model=MedicineDetail, summary="약 상세정보")
async def get_medicine(medicine_id: str, repository: Repository):
    medicine = await repository.get(medicine_id)
    if medicine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "약 정보를 찾을 수 없습니다.")
    return medicine

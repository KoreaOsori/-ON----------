from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession
from app.modules.health_foods import service
from app.modules.health_foods.schemas import HealthFoodDetail, HealthFoodSummary

router = APIRouter(prefix="/health-foods", tags=["health-foods"])


@router.get("", response_model=list[HealthFoodSummary], summary="건강기능식품 검색")
async def search_health_foods(
    db: DbSession,
    q: Annotated[str, Query(max_length=100)] = "",
    form: Annotated[str | None, Query(description="제형 분류 (GET /health-foods/forms)")] = None,
):
    return await service.search(db, q.strip(), form)


@router.get("/forms", summary="건강기능식품 제형 분류")
async def list_forms() -> list[str]:
    return service.form_names()


@router.get("/{health_food_id}", response_model=HealthFoodDetail, summary="건강기능식품 상세정보")
async def get_health_food(health_food_id: str, db: DbSession):
    health_food = await service.get(db, health_food_id)
    if health_food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "건강기능식품 정보를 찾을 수 없습니다.")
    return health_food

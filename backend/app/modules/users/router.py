from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession
from app.modules.users import service
from app.modules.users.models import HealthProfile
from app.modules.users.schemas import REQUIRED_CONSENTS, ConsentUpdate, HealthProfilePayload, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead, summary="내 정보")
async def read_me(user: CurrentUser):
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, summary="회원 탈퇴 (모든 데이터 삭제)")
async def delete_me(user: CurrentUser, db: DbSession):
    await db.delete(user)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/me/consents", status_code=status.HTTP_204_NO_CONTENT, summary="약관·개인정보·건강정보 동의")
async def update_consents(payload: ConsentUpdate, user: CurrentUser, db: DbSession):
    await service.update_consents(db, user, dict(payload.consents))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/health-profile", response_model=HealthProfilePayload | None, summary="건강정보 조회")
async def read_health_profile(user: CurrentUser, db: DbSession):
    profile = await db.get(HealthProfile, user.id)
    return HealthProfilePayload.model_validate(profile) if profile else None


@router.put("/me/health-profile", response_model=HealthProfilePayload, summary="건강정보 저장")
async def save_health_profile(payload: HealthProfilePayload, user: CurrentUser, db: DbSession):
    if not await service.has_required_consents(db, user, REQUIRED_CONSENTS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "건강정보(민감정보) 수집·이용 동의가 필요합니다.")
    profile = await service.upsert_health_profile(db, user, payload)
    return HealthProfilePayload.model_validate(profile)

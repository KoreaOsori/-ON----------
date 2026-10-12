from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import OptionalUser, client_id
from app.integrations.bedrock import ClaudeUnavailableError
from app.integrations.redis import get_redis
from app.modules.chat import service
from app.modules.chat.rate_limit import GuestQuota
from app.modules.chat.schemas import ChatRequest, ChatResponse
from app.modules.medicines.service import MedicineRepository, get_medicine_repository
from app.modules.users.service import summarize_health_profile

router = APIRouter(prefix="/chat", tags=["chat"])


def get_guest_quota() -> GuestQuota:
    return GuestQuota(get_redis())


@router.post("", response_model=ChatResponse, summary="약 질의응답")
async def chat(
    payload: ChatRequest,
    request: Request,
    user: OptionalUser,
    repository: Annotated[MedicineRepository, Depends(get_medicine_repository)],
    quota: Annotated[GuestQuota, Depends(get_guest_quota)],
):
    remaining: int | None = None
    guest_id = client_id(request)
    if user is None:
        remaining = await quota.consume(guest_id)
        if remaining == -1:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                {
                    "code": "GUEST_DAILY_LIMIT",
                    "message": "오늘의 질문을 모두 사용했어요. 로그인 후 이용해 주세요.",
                },
            )
        profile_context = (
            ", ".join(
                filter(
                    None,
                    [
                        payload.profile.gender,
                        payload.profile.age and f"{payload.profile.age}세",
                        payload.profile.pregnant,
                    ],
                )
            )
            if payload.profile
            else None
        )
    else:
        profile_context = summarize_health_profile(user.health_profile) if user.health_profile else None

    try:
        answer, medicine = await service.answer_question(
            repository, payload.question, profile_context or None
        )
    except ClaudeUnavailableError as error:
        if user is None:
            await quota.refund(guest_id)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "잠시 후 다시 시도해 주세요.") from error

    return ChatResponse(
        answer=answer,
        drug=medicine.name if medicine else None,
        sources=[medicine.source] if medicine else [],
        emergency=service.is_emergency(payload.question),
        remaining=remaining,
    )

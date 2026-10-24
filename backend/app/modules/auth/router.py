import uuid

import jwt
from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import create_token, decode_token
from app.modules.auth.schemas import EmailLoginRequest, RefreshRequest, TokenResponse
from app.modules.users.models import User
from app.modules.users.service import get_or_create_email_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user_id: uuid.UUID) -> TokenResponse:
    return TokenResponse(
        access_token=create_token(user_id, "access"),
        refresh_token=create_token(user_id, "refresh"),
        expires_in=settings.access_token_expire_minutes * 60,
    )


# 프로젝트 단계의 간단 로그인: 이메일(아이디)만으로 계정을 만들거나 찾는다. 비밀번호·메일 인증·소셜 로그인은 없다.
# 같은 이메일을 입력하면 누구나 그 계정에 들어갈 수 있으므로, 실제 서비스 전에는 인증을 붙여야 한다.
@router.post("/login", response_model=TokenResponse, summary="이메일(아이디) 로그인 — 없으면 가입")
async def login(payload: EmailLoginRequest, db: DbSession):
    # 서명 키가 기본값이면 토큰을 누구나 만들 수 있으므로 로컬·테스트 밖에서는 로그인을 막는다
    if settings.jwt_secret_key == "change-me" and settings.app_env not in {"local", "test"}:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "로그인을 준비 중입니다. (JWT_SECRET_KEY 미설정)"
        )
    user = await get_or_create_email_user(db, payload.email)
    return _issue_tokens(user.id)


@router.post("/refresh", response_model=TokenResponse, summary="토큰 재발급")
async def refresh(payload: RefreshRequest, db: DbSession):
    try:
        user_id = decode_token(payload.refresh_token, "refresh")
    except jwt.InvalidTokenError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "다시 로그인해 주세요.") from error
    if await db.get(User, uuid.UUID(user_id)) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "다시 로그인해 주세요.")
    return _issue_tokens(uuid.UUID(user_id))

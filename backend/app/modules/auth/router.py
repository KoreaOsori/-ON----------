import secrets
import uuid

import jwt
from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import create_token, decode_token
from app.integrations.redis import get_redis
from app.modules.auth import oauth
from app.modules.auth.schemas import AuthorizeUrlResponse, OAuthTokenRequest, RefreshRequest, TokenResponse
from app.modules.users.models import User
from app.modules.users.service import get_or_create_oauth_user

router = APIRouter(prefix="/auth", tags=["auth"])

STATE_TTL_SECONDS = 600


def _issue_tokens(user_id: uuid.UUID) -> TokenResponse:
    return TokenResponse(
        access_token=create_token(user_id, "access"),
        refresh_token=create_token(user_id, "refresh"),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/oauth/{provider}/authorize", response_model=AuthorizeUrlResponse, summary="소셜 로그인 URL")
async def authorize(provider: oauth.Provider):
    state = secrets.token_urlsafe(24)
    await get_redis().set(f"oauth:state:{state}", provider, ex=STATE_TTL_SECONDS)  # CSRF 방지
    try:
        return AuthorizeUrlResponse(authorize_url=oauth.build_authorize_url(provider, state))
    except oauth.OAuthError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


@router.post("/oauth/{provider}/token", response_model=TokenResponse, summary="소셜 로그인 완료 → JWT 발급")
async def oauth_token(provider: oauth.Provider, payload: OAuthTokenRequest, db: DbSession):
    saved_provider = await get_redis().getdel(f"oauth:state:{payload.state}")
    if saved_provider != provider:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "유효하지 않은 로그인 요청입니다.")
    try:
        profile = await oauth.exchange_code(provider, payload.code, payload.state)
    except oauth.OAuthError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    user = await get_or_create_oauth_user(
        db,
        provider=provider,
        provider_user_id=profile.provider_user_id,
        email=profile.email,
        nickname=profile.nickname,
    )
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


@router.post("/demo-login", response_model=TokenResponse, summary="데모 로그인 (로컬 전용)")
async def demo_login(db: DbSession):
    if not settings.demo_login_enabled or settings.is_production:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    user = await get_or_create_oauth_user(
        db, provider="demo", provider_user_id="demo", email="demo@yakon.local", nickname="데모"
    )
    return _issue_tokens(user.id)

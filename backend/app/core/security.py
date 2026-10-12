import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]


def create_token(subject: uuid.UUID | str, token_type: TokenType) -> str:
    now = datetime.now(UTC)
    expires = (
        timedelta(minutes=settings.access_token_expire_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_expire_days)
    )
    payload = {"sub": str(subject), "type": token_type, "iat": now, "exp": now + expires}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType) -> str:
    """토큰을 검증하고 subject(user id)를 반환한다. 실패 시 jwt.InvalidTokenError."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("토큰 종류가 올바르지 않습니다.")
    return payload["sub"]

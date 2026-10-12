"""카카오 / 네이버 / 구글 OAuth 2.0 (Authorization Code) 연동

흐름
1. 프론트가 GET /auth/oauth/{provider}/authorize 로 authorizeUrl 을 받아 이동
2. 제공자 로그인 후 {OAUTH_REDIRECT_BASE_URL}/{provider}?code=...&state=... 로 돌아옴 (프론트 페이지)
3. 프론트가 POST /auth/oauth/{provider}/token {code, state} 호출 → 백엔드가 code 교환·사용자 조회 후 JWT 발급
"""

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from app.core.config import settings

Provider = Literal["kakao", "naver", "google"]


class OAuthError(Exception):
    pass


@dataclass(frozen=True)
class OAuthProfile:
    provider_user_id: str
    email: str | None
    nickname: str | None


@dataclass(frozen=True)
class ProviderConfig:
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    client_id: str | None
    client_secret: str | None


def _config(provider: Provider) -> ProviderConfig:
    configs = {
        "kakao": ProviderConfig(
            "https://kauth.kakao.com/oauth/authorize",
            "https://kauth.kakao.com/oauth/token",
            "https://kapi.kakao.com/v2/user/me",
            "account_email profile_nickname",
            settings.kakao_client_id,
            settings.kakao_client_secret,
        ),
        "naver": ProviderConfig(
            "https://nid.naver.com/oauth2.0/authorize",
            "https://nid.naver.com/oauth2.0/token",
            "https://openapi.naver.com/v1/nid/me",
            "",
            settings.naver_client_id,
            settings.naver_client_secret,
        ),
        "google": ProviderConfig(
            "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token",
            "https://openidconnect.googleapis.com/v1/userinfo",
            "openid email profile",
            settings.google_client_id,
            settings.google_client_secret,
        ),
    }
    config = configs[provider]
    if not config.client_id:
        raise OAuthError(f"{provider} OAuth 클라이언트가 설정되지 않았습니다.")
    return config


def redirect_uri(provider: Provider) -> str:
    return f"{settings.oauth_redirect_base_url.rstrip('/')}/{provider}"


def build_authorize_url(provider: Provider, state: str) -> str:
    config = _config(provider)
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri(provider),
        "state": state,
    }
    if config.scope:
        params["scope"] = config.scope
    return f"{config.authorize_url}?{urlencode(params)}"


def _parse_profile(provider: Provider, data: dict[str, Any]) -> OAuthProfile:
    if provider == "kakao":
        account = data.get("kakao_account", {})
        return OAuthProfile(str(data["id"]), account.get("email"), account.get("profile", {}).get("nickname"))
    if provider == "naver":
        response = data.get("response", {})
        return OAuthProfile(str(response["id"]), response.get("email"), response.get("nickname"))
    return OAuthProfile(str(data["sub"]), data.get("email"), data.get("name"))


async def exchange_code(provider: Provider, code: str, state: str) -> OAuthProfile:
    config = _config(provider)
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(
            config.token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": config.client_id,
                "client_secret": config.client_secret or "",
                "redirect_uri": redirect_uri(provider),
                "code": code,
                "state": state,
            },
            headers={"Accept": "application/json"},
        )
        if token_response.status_code != 200:
            raise OAuthError(f"{provider} 토큰 교환 실패: {token_response.status_code}")
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise OAuthError(f"{provider} 액세스 토큰이 없습니다.")
        profile_response = await client.get(
            config.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
        )
        if profile_response.status_code != 200:
            raise OAuthError(f"{provider} 사용자 정보 조회 실패: {profile_response.status_code}")
    return _parse_profile(provider, profile_response.json())

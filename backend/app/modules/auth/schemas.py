from typing import Literal

from app.core.schemas import CamelModel


class AuthorizeUrlResponse(CamelModel):
    authorize_url: str


class OAuthTokenRequest(CamelModel):
    code: str
    state: str


class RefreshRequest(CamelModel):
    refresh_token: str


class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int

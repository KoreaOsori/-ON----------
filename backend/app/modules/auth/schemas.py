from typing import Literal

from pydantic import Field, field_validator

from app.core.schemas import CamelModel


class EmailLoginRequest(CamelModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    # 형식 검사 전에 공백·대소문자를 정리 (Hong@Example.com 과 hong@example.com 은 같은 계정)
    @field_validator("email", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class RefreshRequest(CamelModel):
    refresh_token: str


class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int

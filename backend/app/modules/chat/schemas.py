from pydantic import Field

from app.core.schemas import CamelModel


class GuestProfile(CamelModel):
    """비회원 임시 건강정보. 요청 처리에만 사용하고 저장하지 않는다."""

    gender: str = ""
    age: str = ""
    pregnant: str = ""


class ChatRequest(CamelModel):
    question: str = Field(min_length=1, max_length=1000)
    profile: GuestProfile | None = None


class ChatResponse(CamelModel):
    answer: str
    drug: str | None
    sources: list[str]
    emergency: bool
    remaining: int | None = Field(description="비회원의 오늘 남은 질문 수 (회원은 null)")

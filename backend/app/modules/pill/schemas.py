from pydantic import Field

from app.core.schemas import CamelModel

# 응답은 워커(yakon_pill)가 만든 camelCase JSON 을 그대로 전달한다 — 문장·버튼·후보 구조를 백엔드에서 다시 만들지 않음


class PillAnalyzeRequest(CamelModel):
    front_key: str = Field(pattern=r"^pill/")
    back_key: str | None = Field(default=None, pattern=r"^pill/")
    shape: str | None = Field(default=None, max_length=20)
    # 사용자가 동의했을 때만 배경 제거된 알약 조각 저장
    save_crops: bool = False
    prev_session_id: str | None = None


class PillRejectRequest(CamelModel):
    session_id: str
    from_step: str | None = None


class PillImprintChoiceRequest(CamelModel):
    session_id: str
    choice: str = Field(max_length=40)


class PillRefineRequest(CamelModel):
    session_id: str
    imprint_front: str | None = Field(default=None, max_length=40)
    imprint_back: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)


class PillConfirmRequest(CamelModel):
    session_id: str
    item_seq: str
    user_question: str = Field(default="", max_length=500)

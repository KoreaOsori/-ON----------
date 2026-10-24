"""
요청·응답 형식. JSON 은 camelCase (백엔드 CamelModel 과 같은 규칙), 파이썬 속성은 snake_case.

응답은 yakon_pill / yakon_rx 가 돌려준 dict 를 그대로 쓰되 키만 camelCase 로 바꾼다 (camelize).
→ 식별 모듈의 출력 구조·문장을 워커가 다시 만들지 않기 위해
"""
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def camelize(obj):
    """dict 키를 camelCase 로 (값은 그대로). 숫자 키·한글 키는 바꾸지 않는다"""
    if isinstance(obj, dict):
        return {(to_camel(k) if isinstance(k, str) and "_" in k else k): camelize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [camelize(v) for v in obj]
    return obj


# ---------------------------------------------------------------- 알약
class PillAnalyzeRequest(CamelModel):
    front_key: str
    # 한 면만 찍은 경우 비워 두면 앞면 사진을 두 면으로 사용 (정확도는 낮아질 수 있음)
    back_key: str | None = None
    shape: str | None = None
    save_crops: bool = False
    # 재촬영(retake) 이후의 분석이면 이전 세션 → 시도 횟수를 이어받아 give_up 단계로 갈 수 있게
    prev_session_id: str | None = None


class PillRejectRequest(CamelModel):
    session_id: str
    from_step: str | None = None


class PillImprintChoiceRequest(CamelModel):
    session_id: str
    choice: str


class PillRefineRequest(CamelModel):
    session_id: str
    imprint_front: str | None = Field(default=None, max_length=40)
    imprint_back: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)


class PillConfirmRequest(CamelModel):
    session_id: str
    item_seq: str
    user_question: str = Field(default="", max_length=500)


# ---------------------------------------------------------------- 처방전·약봉투
class RxAnalyzeRequest(CamelModel):
    key: str


class RxConfirmRequest(CamelModel):
    session_id: str
    drug_index: int = Field(ge=0)
    item_seq: str

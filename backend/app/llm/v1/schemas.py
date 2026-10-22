from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductInput(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    product_type: Literal["drug", "health_food"] | None = None
    product_key: str | None = Field(None, min_length=1, max_length=200,
                                    description="확인 질문에서 선택한 후보의 product_key")


class AskRequest(StrictModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"question": "이 제품의 효능을 알려주세요.", "products": ["DB에 저장된 제품명"], "model": "haiku"},
        {"question": "이 두 제품을 함께 먹어도 되나요?", "products": ["첫 번째 제품명", "두 번째 제품명"],
         "model": "sonnet"},
    ]})
    question: str = Field(min_length=1, max_length=1000)
    products: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=8, description="OCR 제품명 목록. 유형과 ID는 서버에서 조회합니다.")
    model: Literal["sonnet", "haiku"] | None = None
    selections: dict[int, str] = Field(default_factory=dict,
        description="재확인할 때만 사용: products의 0부터 시작하는 위치 → 선택한 후보 product_key")

    @model_validator(mode="after")
    def check_selections(self):
        if any(i < 0 or i >= len(self.products) or len(key) > 200 for i, key in self.selections.items()):
            raise ValueError("잘못된 후보 선택")
        return self



class AskResponse(BaseModel):
    status: Literal["answered", "needs_clarification", "insufficient_data", "refused"]
    answer: str
    products: list[dict] = Field(default_factory=list)
    clarifications: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    interaction_checks: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_id: str | None = None
    usage: dict = Field(default_factory=dict)
    latency_ms: int = 0
    run_id: str | None = None
    detected_intent: str | None = None


class IngredientProduct(StrictModel):
    product_key: str = Field(pattern=r"^drug:.+", max_length=200)
    codes: list[str] = Field(min_length=1, max_length=100)
    complete: bool = False
    source: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_codes(self):
        if any(not code.strip() or code != code.strip() for code in self.codes):
            raise ValueError("성분 코드는 공백 없이 입력하세요.")
        self.codes = sorted(set(self.codes))
        return self


class ContraindicationRule(StrictModel):
    rule_id: str = Field(min_length=1, max_length=200)
    left_codes: list[str] = Field(min_length=1, max_length=100)
    right_codes: list[str] = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=10000)
    conditions: str = Field(default="", max_length=10000)
    source: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_codes(self):
        for codes in (self.left_codes, self.right_codes):
            if any(not code.strip() or code != code.strip() for code in codes):
                raise ValueError("성분 코드는 공백 없이 입력하세요.")
        return self


class SafetyBundle(StrictModel):
    run_id: str = Field(min_length=1, max_length=200)
    code_system: Literal["DUR"] = "DUR"
    rules_complete: bool = False
    source: str = Field(min_length=1, max_length=1000)
    products: list[IngredientProduct]
    rules: list[ContraindicationRule]

    @model_validator(mode="after")
    def unique_keys(self):
        for values in ([p.product_key for p in self.products], [r.rule_id for r in self.rules]):
            if len(values) != len(set(values)):
                raise ValueError("중복 제품 또는 규칙 ID")
        return self

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductInput(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    product_type: Literal["drug", "health_food"] | None = None
    product_key: str | None = Field(None, min_length=1, max_length=200,
                                    description="확인 질문에서 선택한 후보의 product_key")


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    intent: Literal["efficacy", "interactions"]
    products: list[ProductInput] = Field(min_length=1, max_length=8)
    model: Literal["sonnet", "haiku"] | None = None

    @model_validator(mode="after")
    def validate_pair(self):
        if self.intent == "interactions" and len(self.products) < 2:
            raise ValueError("병용 확인에는 제품을 2개 이상 입력하세요.")
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

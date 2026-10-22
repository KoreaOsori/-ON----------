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
        default_factory=list, max_length=8, description="OCR 제품명 목록. 질문에 제품명이 있으면 생략 가능합니다.")
    model: Literal["sonnet", "haiku"] | None = None


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["answered", "needs_clarification", "insufficient_data", "refused", "error"]
    answer: str
    usage: dict = Field(default_factory=dict)


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

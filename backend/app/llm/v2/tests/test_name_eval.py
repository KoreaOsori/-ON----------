"""제품명 변형 평가 코드 테스트: 변형 생성, 결과 분류, 집계."""
from app.llm.v2.evaluation.name_eval import classify, evaluate_names, format_report, make_variants
from app.llm.v2.search import SearchOutcome


def product(key):
    return {"product_key": key, "product_name": key, "manufacturer": "m"}


def test_make_variants_with_parentheses():
    v = make_variants("다이크로짇정(히드로클로로티아지드)")
    assert v["original"] == "다이크로짇정(히드로클로로티아지드)"
    assert v["no_paren"] == "다이크로짇정"
    assert v["fullwidth"] == "다이크로짇정（히드로클로로티아지드）"
    assert v["wrong_paren"] == "다이크로짇정(다른성분)"
    assert v["spaced"].replace(" ", "") == v["original"] and v["spaced"].count(" ") == 1
    name = v["original"]
    assert v["half_prefix"] == name[: len(name) // 2] and 3 <= len(v["half_prefix"]) < len(name)


def test_make_variants_nested_and_multiple_groups():
    v = make_variants("가나정(다라(마바))(수출용)")
    assert v["no_paren"] == "가나정"
    assert "다른성분" in v["wrong_paren"] and v["wrong_paren"] != v["original"]  # 가장 안쪽 괄호부터 바뀐다


def test_make_variants_without_parentheses_and_short_names():
    v = make_variants("타이레놀정")
    assert set(v) == {"original", "spaced", "half_prefix"}  # 괄호 변형은 만들지 않는다
    assert make_variants("가나")["original"] == "가나" and set(make_variants("가나")) == {"original"}


def test_classify_outcomes():
    one = SearchOutcome("ok", products=[product("drug:1")])
    assert classify(one, "drug:1") == "exact_hit"
    assert classify(SearchOutcome("ok", products=[product("drug:1")], approximate=True), "drug:1") == "approx_hit"
    assert classify(one, "drug:2") == "wrong_product"
    many = SearchOutcome("needs_clarification", products=[product("drug:1"), product("drug:2")])
    assert classify(many, "drug:2") == "clarify_incl" and classify(many, "drug:9") == "clarify_excl"
    assert classify(SearchOutcome("ambiguous_product", products=[]), "drug:1") == "too_many"
    named = SearchOutcome("ok", products=[{"product_key": "drug:2", "product_name": "고려홍삼정", "manufacturer": "m"}])
    assert classify(named, "drug:1", "고려홍삼정") == "sibling"             # 입력이 다른 제품의 이름 그대로
    assert classify(named, "drug:1", "고려홍삼정(다른성분)") == "sibling"  # 괄호를 떼면 다른 제품의 이름
    assert classify(named, "drug:1", "고려 홍삼정") == "sibling"           # 공백 차이
    assert classify(named, "drug:1", "전혀다른이름") == "wrong_product"
    assert classify(named, "drug:1") == "wrong_product"                    # typed 가 없으면 구분하지 않는다
    assert classify(SearchOutcome("product_not_found"), "drug:1") == "not_found"
    assert classify(SearchOutcome("no_snapshot"), "drug:1") == "other"


async def test_evaluate_names_counts_and_examples():
    async def lookup(name):
        if name == "다이크로짇정(히드로클로로티아지드)":
            return SearchOutcome("ok", products=[product("drug:1")])
        if name == "다이크로짇정":
            return SearchOutcome("ok", products=[product("drug:1")], approximate=True)
        return SearchOutcome("product_not_found")

    report = await evaluate_names([{"product_key": "drug:1", "product_name": "다이크로짇정(히드로클로로티아지드)"}], lookup)
    assert report["original"]["counts"]["exact_hit"] == 1 and report["original"]["n"] == 1
    assert report["no_paren"]["counts"]["approx_hit"] == 1
    assert report["fullwidth"]["counts"]["not_found"] == 1 and report["fullwidth"]["examples"]
    assert report["fullwidth"]["examples"][0][1] == "not_found"
    text = format_report(report)
    assert "no_paren" in text and "wrong_product" in text and "[fullwidth/not_found]" in text


async def test_evaluate_names_no_applicable_kind_prints_note():
    async def lookup(name):
        return SearchOutcome("ok", products=[product("drug:1")])

    report = await evaluate_names([{"product_key": "drug:1", "product_name": "타이레놀정"}], lookup)
    assert report["no_paren"]["n"] == 0
    assert "해당 제품 없음" in format_report(report)

"""서비스 페이지 점검(2026-10-23)에서 나온 문제의 회귀 테스트: 위기 표현, 제품 수, 띄어 쓴 이름, '찾지 못함' 상태, 프롬프트 규칙."""
from app.llm.v3.agent import DrugInfoAgent, says_not_found
from app.llm.v3.contra_tool import ContraindicationTool
from app.llm.v3.gold_safety import GoldContraStore
from app.llm.v3.harness import Limits
from app.llm.v3.prompts import CRISIS_ANSWER, SYSTEM_PROMPT, TOO_MANY_PRODUCTS_ANSWER
from app.llm.v3.safety import is_crisis
from app.llm.v3.search import find_products
from app.llm.v3.tests.helpers import FakeReader, FakeReaderFactory, ScriptedModel, make_settings, response, text_block, tool_use_block
from app.llm.v3.tests.test_agent import FOUND, FakeTool
from app.llm.v3.tests.test_v3_integration import gold_reader
from app.llm.v3.tools import Evidence, ToolResult


def test_crisis_catches_hoarding_and_wish_to_disappear():
    for q in ("요즘 너무 힘들어서 수면제를 모아두고 있어요", "진통제 사 모아 놨어요", "살기 싫어요", "그냥 사라지고 싶어요",
              "내일 아침 깨어나지 않았으면 좋겠어요"):
        assert is_crisis(q), q
    for q in ("수면제 보관 방법", "약 정리함에 모아서 보관해도 돼요?", "약을 모아서 버려도 되나요?", "셉트린정 먹다가 그만 먹어도 돼요?"):
        assert not is_crisis(q), q


async def test_crisis_question_skips_model():
    model = ScriptedModel()
    result = await DrugInfoAgent(model, FakeTool(FOUND), Limits()).run("요즘 너무 힘들어서 수면제를 모아두고 있어요")
    assert result.stop_reason == "crisis" and result.answer == CRISIS_ANSWER and model.calls == []


def test_limit_is_ten_products_everywhere():
    from app.llm.v3.contra_tool import MAX_PRODUCTS, build_contra_spec
    from app.llm.v3.names import MAX_GIVEN_PRODUCTS, clean_product_names
    from app.llm.v3.prompts import CONTRA_PROMPT_ADDENDUM

    assert MAX_PRODUCTS == 10 and MAX_GIVEN_PRODUCTS == 10
    assert build_contra_spec()["input_schema"]["properties"]["products"]["maxItems"] == 10
    assert "10개까지" in TOO_MANY_PRODUCTS_ANSWER and "11개 이상" in CONTRA_PROMPT_ADDENDUM and "2~10개" in CONTRA_PROMPT_ADDENDUM
    assert len(clean_product_names([f"약{i}" for i in range(12)])) == 10


async def test_ten_products_are_checked_not_refused():
    reader = gold_reader()
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(reader), GoldContraStore())
    result = await tool.run({"products": [f"없는약{i}" for i in range(10)]})
    assert result.clarification != TOO_MANY_PRODUCTS_ANSWER and reader.calls  # 10개는 한도 안이라 실제로 조회한다


async def test_contra_tool_with_eleven_products_returns_limit_guidance_without_db():
    reader = gold_reader()
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(reader), GoldContraStore())
    result = await tool.run({"products": [f"약{i}" for i in range(11)]})
    assert result.is_error and result.clarification == TOO_MANY_PRODUCTS_ANSWER and reader.calls == []


async def test_same_product_twice_asks_for_another_product():
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(gold_reader()), GoldContraStore())
    result = await tool.run({"products": ["셉트린정", "셉트린 정"]})
    assert result.is_error and "서로 다른 약이 2개 이상" in result.clarification and "'셉트린정'" in result.clarification
    model = ScriptedModel(response(text_block("다른 약이 필요해요")))
    answer = await DrugInfoAgent(model, FakeTool(FOUND), Limits()).run("같이 먹어도 돼요?", products=["셉트린정", "셉트린 정"])
    assert answer.stop_reason == "needs_clarification" and "서로 다른 약이 2개 이상" in answer.answer


async def test_single_product_info_question_is_not_turned_into_combination_guidance():
    model = ScriptedModel(response(text_block("어떤 약인지 알려 주세요")))
    answer = await DrugInfoAgent(model, FakeTool(FOUND), Limits()).run("이 약 언제 먹어요?", products=["셉트린정"])
    assert answer.stop_reason == "no_evidence" and "서로 다른 약" not in answer.answer


def _catalog_reader(names):
    rows = [{"product_key": f"drug:{i}", "product_name": n, "manufacturer": "M", "product_type": "drug"} for i, n in enumerate(names)]

    def handler(sql, params):
        value = params.get("value", "")
        if "= :value" in sql:
            return [r for r in rows if r["product_name"].lower() == value]
        if value.startswith("%"):
            return [r for r in rows if value.strip("%") in r["product_name"].lower()][: params["limit"]]
        return [r for r in rows if r["product_name"].lower().startswith(value.rstrip("%"))][: params["limit"]]
    return FakeReader(handler)


async def test_spaced_name_with_strength_falls_back_to_brand_and_narrows_by_number():
    names = ["타이레놀정500밀리그람(아세트아미노펜)", "타이레놀콜드-에스정", "타이레놀8시간이알서방정(아세트아미노펜)", "타이레놀산500밀리그램(아세트아미노펜)"]
    found = await find_products(_catalog_reader(names), "run1", "타이레놀 500mg")
    assert found["mode"] == "brand" and found["approximate"]
    assert [p["product_name"] for p in found["products"]] == [names[0], names[3]]
    plain = await find_products(_catalog_reader(names), "run1", "타이레놀 시럽")  # 숫자가 없으면 브랜드 전체가 후보
    assert len(plain["products"]) == 4
    none = await find_products(_catalog_reader(names), "run1", "없는약 500mg")
    assert none["mode"] == "not_found"


def test_says_not_found_reads_only_the_first_sentence():
    assert says_not_found("셉트린정의 보관 방법은 등록된 정보에서 확인할 수 없어요. 포장을 확인해 주세요.")
    assert says_not_found("술과 함께 복용하는 것에 대해 직접 적힌 내용을 찾지 못했어요.\n다만 …")
    assert not says_not_found("등록된 병용금기 자료에서는 확인되지 않았어요. 다만 안전하다는 뜻은 아니에요.")
    assert not says_not_found("성인은 1회 1정 복용해요. 그 밖의 내용은 확인할 수 없어요.")


async def test_grounded_answer_that_says_not_found_gets_no_evidence_status():
    found = ToolResult("[출처 | 셉트린정 | 개요 | 유사도 0.7]\n삼일제약", [Evidence("셉트린정", "삼일제약", "overview", 1)])
    model = ScriptedModel(
        response(tool_use_block("t1", "search_drug_info", product_name="셉트린정", question="보관")),
        response(text_block("셉트린정의 보관 방법은 등록된 정보에서 확인할 수 없어요.")),
    )
    result = await DrugInfoAgent(model, FakeTool(found), Limits()).run("셉트린정 보관 방법")
    assert result.stop_reason == "no_evidence" and result.answer.startswith("셉트린정의 보관 방법은")


def test_prompt_has_wording_rules_from_page_check():
    for phrase in ("밀리그람", "음주", "만 0세", "아무나 먹는 약이 아니다", "구간", "머리가 아픈데"):
        assert phrase in SYSTEM_PROMPT, phrase


async def test_too_many_marker_from_model_becomes_limit_guidance():
    model = ScriptedModel(response(text_block("[제품수초과]")))
    result = await DrugInfoAgent(model, FakeTool(FOUND), Limits()).run(
        "셉트린정이랑 게보린정이랑 판콜에이내복액 같이 먹어도 돼요?", products=["타이레놀정500밀리그람", "아스피린", "홍삼정"]
    )
    assert result.stop_reason == "needs_clarification" and result.answer == TOO_MANY_PRODUCTS_ANSWER


async def test_product_found_but_no_relevant_paragraph_names_the_product():
    from app.llm.v3.search import SearchOutcome
    from app.llm.v3.tools import format_outcome

    no_match = format_outcome(SearchOutcome("ok", "run1", products=[{"product_name": "셉트린정"}], hits=[]), "셉트린정")
    assert no_match.unmatched == ["셉트린정"] and not no_match.terminal
    model = ScriptedModel(
        response(tool_use_block("t1", "search_drug_info", product_name="셉트린정", question="술")),
        response(text_block("확인할 수 없어요")),
    )
    result = await DrugInfoAgent(model, FakeTool(no_match), Limits()).run("셉트린정 먹고 술 마셔도 돼요?")
    assert result.stop_reason == "no_evidence" and "'셉트린정'의 등록된 정보에서는 물어보신 내용을 찾지 못했어요" in result.answer
    assert "다시 질문해 주세요" not in result.answer


def test_prompt_and_tool_spec_ask_for_names_as_written():
    from app.llm.v3.prompts import CONTRA_PROMPT_ADDENDUM
    from app.llm.v3.tools import build_tool_spec

    assert "[제품수초과]" in CONTRA_PROMPT_ADDENDUM and "interactions(상호작용)" in CONTRA_PROMPT_ADDENDUM
    assert "타이레놀 8시간" in SYSTEM_PROMPT
    assert "줄이거나 바꾸지 않고" in build_tool_spec(False)["input_schema"]["properties"]["product_name"]["description"]

"""에이전트 루프 테스트: 가짜 Claude(ScriptedModel) + 가짜 도구로 정책을 검증한다."""
import os

from app.llm.v2 import agent as agent_module
from app.llm.v2.agent import DrugInfoAgent, answer
from app.llm.v2.harness import ALLOWED_TOOLS, Limits, ToolNotAllowedError, assert_allowed_tool
from app.llm.v2.prompts import (
    BUDGET_ANSWER,
    CRISIS_ANSWER,
    EMERGENCY_NOTICE,
    ERROR_ANSWER,
    FORCED_FINAL_HINT,
    NO_EVIDENCE_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    SAFETY_FOOTER,
    TIMEOUT_ANSWER,
)
from app.llm.v2.safety import is_crisis, is_emergency
from app.llm.v2.tests.helpers import ScriptedModel, make_settings, raises, response, text_block, tool_use_block
from app.llm.v2.tools import TOOL_NAME, Evidence, ToolResult, build_tool_spec

FOUND = ToolResult(
    "[출처 | 타이레놀 | 용법·용량 | 유사도 0.900]\n성인은 1회 1~2정",
    [Evidence("타이레놀", "M", "usage", 1)],
)
MISSING = ToolResult("[검색 결과 없음] '없는약'과(와) 일치하는 제품을 찾지 못했습니다.")


class FakeTool:
    """DrugSearchTool 가짜: 미리 정한 결과를 돌려주고 호출 인자를 기록한다."""

    def __init__(self, *results, delay=0.0):
        self._results = list(results)
        self.calls = []
        self._delay = delay

    @property
    def spec(self):
        return build_tool_spec(False)

    async def run(self, arguments):
        import asyncio

        self.calls.append(arguments)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


def make_agent(model, tool, **limits):
    return DrugInfoAgent(model, tool, Limits(**limits))


def search_call(tool_id="t1", **extra):
    args = {"product_name": "타이레놀", "question": "복용법"}
    args.update(extra)
    return tool_use_block(tool_id, TOOL_NAME, **args)


async def test_grounded_answer_gets_footer_and_sources_from_evidence():
    model = ScriptedModel(response(search_call()), response(text_block("타이레놀은 1회 1~2정이에요.")))
    tool = FakeTool(FOUND)
    result = await make_agent(model, tool).run("타이레놀 복용법 알려줘", "나이: 30")
    assert result.grounded and result.stop_reason == "done" and result.rounds == 1
    assert result.answer.endswith(SAFETY_FOOTER) and "1회 1~2정" in result.answer
    assert result.sources == ["타이레놀 · 용법·용량"] and result.tools_used == [TOOL_NAME]
    assert tool.calls == [{"product_name": "타이레놀", "question": "복용법"}]
    # 두 번째 호출에는 assistant tool_use 와 그에 대한 tool_result 가 이어져야 한다.
    second = model.calls[1]["messages"]
    assert second[1]["role"] == "assistant" and second[1]["content"][0]["type"] == "tool_use"
    assert second[2]["role"] == "user" and second[2]["content"][0]["tool_use_id"] == "t1"
    assert "[사용자 정보]\n나이: 30" in model.calls[0]["messages"][0]["content"]
    assert model.calls[0]["tools"][0]["name"] == TOOL_NAME


async def test_no_tool_call_means_no_evidence_answer_regardless_of_model_text():
    model = ScriptedModel(response(text_block("타이레놀은 하루 4000mg까지 드셔도 됩니다.")))
    result = await make_agent(model, FakeTool(FOUND)).run("타이레놀 얼마나 먹어도 돼?")
    assert result.answer == OUT_OF_SCOPE_ANSWER and not result.grounded and result.stop_reason == "no_evidence"
    assert "4000" not in result.answer and result.sources == []


async def test_not_found_result_is_not_evidence():
    model = ScriptedModel(response(search_call()), response(text_block("그 약은 안전해요.")))
    result = await make_agent(model, FakeTool(MISSING)).run("없는약 괜찮아?")
    assert result.answer == NO_EVIDENCE_ANSWER and result.tools_used == [TOOL_NAME] and not result.grounded


async def test_disallowed_tool_is_never_executed():
    model = ScriptedModel(
        response(tool_use_block("t1", "run_sql", query="DROP TABLE x")),
        response(text_block("확인할 수 없어요.")),
    )
    tool = FakeTool(FOUND)
    result = await make_agent(model, tool).run("질문")
    assert tool.calls == [] and result.tools_used == []
    blocked = model.calls[1]["messages"][2]["content"][0]
    assert blocked["is_error"] is True and blocked["tool_use_id"] == "t1"
    assert result.answer == OUT_OF_SCOPE_ANSWER  # 허용되지 않은 도구는 실행되지 않았으므로 '찾아봤지만 없음'이 아니다


async def test_parallel_tool_uses_all_get_results():
    model = ScriptedModel(
        response(search_call("a"), search_call("b", question="주의사항")),
        response(text_block("정리했어요.")),
    )
    tool = FakeTool(FOUND)
    result = await make_agent(model, tool).run("질문")
    ids = [b["tool_use_id"] for b in model.calls[1]["messages"][2]["content"]]
    assert ids == ["a", "b"] and len(tool.calls) == 2 and result.grounded


async def test_call_limit_blocks_extra_tool_calls_but_keeps_loop_valid():
    model = ScriptedModel(
        response(search_call("a"), search_call("b"), search_call("c")),
        response(text_block("답")),
    )
    tool = FakeTool(FOUND)
    await make_agent(model, tool, max_tool_calls=2).run("질문")
    results = model.calls[1]["messages"][2]["content"]
    assert len(tool.calls) == 2 and results[2]["is_error"] is True


async def test_round_limit_forces_final_answer():
    model = ScriptedModel(
        response(search_call("a")),
        response(search_call("b")),
        response(text_block("지금까지 근거로 답해요.")),
    )
    result = await make_agent(model, FakeTool(FOUND), max_tool_rounds=2).run("질문")
    assert result.rounds == 2 and result.grounded
    last_user = model.calls[2]["messages"][-1]["content"]
    assert last_user[-1] == {"type": "text", "text": FORCED_FINAL_HINT}  # 마지막 라운드 뒤 힌트


async def test_model_keeps_asking_for_tools_after_limit_stops_with_budget_answer():
    model = ScriptedModel(response(search_call("a")), response(search_call("b")))
    tool = FakeTool(FOUND)
    result = await make_agent(model, tool, max_tool_rounds=1).run("질문")
    assert result.answer == BUDGET_ANSWER and result.stop_reason == "budget" and len(tool.calls) == 1
    assert not result.grounded and result.sources == []


async def test_time_limit_on_model_call():
    model = ScriptedModel(response(text_block("늦은 답")), delay=0.5)
    result = await make_agent(model, FakeTool(FOUND), max_seconds=0.05).run("질문")
    assert result.answer == TIMEOUT_ANSWER and result.stop_reason == "timeout"


async def test_time_limit_on_tool_call():
    model = ScriptedModel(response(search_call()), response(text_block("답")))
    result = await make_agent(model, FakeTool(FOUND, delay=0.5), max_seconds=0.1).run("질문")
    assert result.answer == TIMEOUT_ANSWER


async def test_model_error_is_contained_and_not_leaked():
    model = ScriptedModel(RuntimeError("AccessDenied arn:aws:iam::111111111111:role/x"))
    result = await make_agent(model, FakeTool(FOUND)).run("질문")
    assert result.answer == ERROR_ANSWER and result.stop_reason == "error" and "arn:" not in result.answer


async def test_refusal_stop_reason():
    model = ScriptedModel(response(text_block("거절"), stop_reason="refusal"))
    result = await make_agent(model, FakeTool(FOUND)).run("질문")
    assert result.answer == ERROR_ANSWER and result.stop_reason == "refusal"


async def test_emergency_notice_is_prepended():
    model = ScriptedModel(response(search_call()), response(text_block("복용법이에요.")))
    result = await make_agent(model, FakeTool(FOUND)).run("타이레놀 먹었는데 호흡곤란이 와요")
    assert result.emergency and result.answer.startswith(EMERGENCY_NOTICE) and result.grounded
    model = ScriptedModel(RuntimeError("x"))
    result = await make_agent(model, FakeTool(FOUND)).run("호흡곤란이 와요")
    assert result.answer.startswith(EMERGENCY_NOTICE)  # 모델이 실패해도 응급 안내는 나간다


async def test_crisis_skips_model_and_tools():
    model = ScriptedModel()
    tool = FakeTool(FOUND)
    result = await make_agent(model, tool).run("약을 한꺼번에 다 먹고 죽고 싶어요")
    assert result.answer == CRISIS_ANSWER and result.stop_reason == "crisis"
    assert model.calls == [] and tool.calls == []


async def test_empty_and_long_questions():
    model = ScriptedModel(response(text_block("x")))
    assert (await make_agent(model, FakeTool(FOUND)).run("   ")).stop_reason == "empty" and model.calls == []
    await make_agent(model, FakeTool(FOUND), max_question_chars=10).run("가" * 100)
    assert model.calls[0]["messages"][0]["content"].endswith("가" * 10)


def test_safety_patterns():
    assert is_emergency("숨이 안 쉬어져요") and is_emergency("얼굴이 붓고 두드러기가 나요") and is_emergency("쇼크가 온 것 같아요")
    assert not is_emergency("타이레놀 복용법 알려줘")
    assert is_crisis("죽고 싶어요") and not is_crisis("두통약 추천해줘")


def test_whitelist():
    assert ALLOWED_TOOLS == {TOOL_NAME, "check_contraindication"}
    assert_allowed_tool(TOOL_NAME)
    with raises(ToolNotAllowedError):
        assert_allowed_tool("bash")


async def test_answer_entrypoint_never_raises_when_agent_cannot_be_built():
    from app.llm.v2.config import ConfigError

    def broken_build(settings=None):
        raise ConfigError("DB host/name 설정이 필요합니다.")

    original = agent_module.build_agent
    agent_module._agent = None
    agent_module.build_agent = broken_build
    try:
        result = await answer("타이레놀 복용법", None)
    finally:
        agent_module.build_agent = original
    assert result.answer == ERROR_ANSWER and result.stop_reason == "error"


CLARIFY = ToolResult(
    "[확인 필요] ...",
    candidates=[
        {"product_key": "drug:1", "product_name": "대한포도당주사액(5%)", "manufacturer": "대한약품"},
        {"product_key": "drug:2", "product_name": "대한포도당주사액(10%)", "manufacturer": "대한약품"},
    ],
)


async def test_clarification_answer_is_built_by_code_not_by_model():
    model = ScriptedModel(response(search_call()), response(text_block("5%가 맞을 거예요. 보통 1회 500mL입니다.")))
    result = await make_agent(model, FakeTool(CLARIFY)).run("대한포도당주사액 용법 알려줘")
    assert result.stop_reason == "needs_clarification" and not result.grounded and result.sources == []
    assert "대한포도당주사액(5%)" in result.answer and "대한포도당주사액(10%)" in result.answer
    assert "500mL" not in result.answer  # 모델이 임의로 고른 내용은 쓰지 않는다
    assert [c["product_key"] for c in result.candidates] == ["drug:1", "drug:2"]


async def test_clarification_is_dropped_when_evidence_was_found_later():
    model = ScriptedModel(response(search_call("a")), response(search_call("b", product_key="drug:1")), response(text_block("정리")))
    result = await make_agent(model, FakeTool(CLARIFY, FOUND)).run("대한포도당주사액 용법")
    assert result.grounded and result.candidates == [] and result.stop_reason == "done"


async def test_caller_selected_product_key_overrides_model_arguments():
    model = ScriptedModel(response(search_call(product_key="drug:99")), response(text_block("답")))
    tool = FakeTool(FOUND)
    result = await make_agent(model, tool).run("대한포도당주사액 용법", None, product_key="drug:2")
    assert tool.calls[0]["product_key"] == "drug:2" and result.grounded
    assert "[선택한 제품 ID]\ndrug:2" in model.calls[0]["messages"][0]["content"]


async def test_tool_trace_records_arguments_and_result_head():
    model = ScriptedModel(
        response(tool_use_block("t1", TOOL_NAME, product_name="타이레놀", question="복용법", extra="무시")),
        response(text_block("1회 1~2정이에요.")),
    )
    agent = make_agent(model, FakeTool(FOUND))
    result = await agent.run("타이레놀 복용법")
    assert len(result.tool_trace) == 1
    entry = result.tool_trace[0]
    assert entry["arguments"] == {"product_name": "타이레놀", "question": "복용법"}  # 알려진 키만 기록
    assert entry["result_head"].startswith("[출처 | 타이레놀") and len(entry["result_head"]) <= 80


# --------------------------------------------------------------------------- 병용금기 도구

CONTRA_FOUND = ToolResult(
    "[출처 | 와파린정 × 아스피린 | 병용금기(DUR)]\n금기 내용: 출혈 위험 증가",
    [Evidence("와파린정 × 아스피린", "", "contraindication", 1, display="와파린정 × 아스피린")],
)


class FakeContraTool(FakeTool):
    @property
    def spec(self):
        from app.llm.v2.contra_tool import build_contra_spec

        return build_contra_spec()


def contra_call(tool_id="c1", **args):
    from app.llm.v2.contra_tool import CONTRA_TOOL_NAME

    return tool_use_block(tool_id, CONTRA_TOOL_NAME, **(args or {"products": ["와파린정", "아스피린"]}))


async def test_contra_tool_is_offered_with_prompt_addendum_and_grounds_the_answer():
    from app.llm.v2.contra_tool import CONTRA_TOOL_NAME
    from app.llm.v2.prompts import CONTRA_PROMPT_ADDENDUM, SYSTEM_PROMPT

    model = ScriptedModel(response(contra_call()), response(text_block("등록된 자료에서 병용금기로 확인돼요.")))
    contra = FakeContraTool(CONTRA_FOUND)
    agent = DrugInfoAgent(model, FakeTool(FOUND), Limits(), contra_tool=contra)
    result = await agent.run("와파린이랑 아스피린 같이 먹어도 돼요?", product_key="drug:1")
    assert [t["name"] for t in model.calls[0]["tools"]] == [TOOL_NAME, CONTRA_TOOL_NAME]
    assert model.calls[0]["system"] == SYSTEM_PROMPT + CONTRA_PROMPT_ADDENDUM
    assert result.grounded and result.sources == ["와파린정 × 아스피린 · 병용금기(DUR)"] and result.tools_used == [CONTRA_TOOL_NAME]
    assert contra.calls == [{"products": ["와파린정", "아스피린"]}]  # 호출자가 정한 product_key 는 검색 도구에만 주입된다
    assert result.answer.endswith(SAFETY_FOOTER)


async def test_contra_tool_is_off_when_not_configured():
    from app.llm.v2.contra_tool import CONTRA_TOOL_NAME
    from app.llm.v2.prompts import SYSTEM_PROMPT

    model = ScriptedModel(response(contra_call()), response(text_block("괜찮아요.")))
    result = await make_agent(model, FakeTool(FOUND)).run("와파린이랑 아스피린 같이 먹어도 돼요?")
    assert [t["name"] for t in model.calls[0]["tools"]] == [TOOL_NAME] and model.calls[0]["system"] == SYSTEM_PROMPT
    assert "check_contraindication" not in SYSTEM_PROMPT
    tool_result = model.calls[1]["messages"][2]["content"][0]
    assert tool_result["is_error"] and "사용할 수 없는 도구" in tool_result["content"]
    assert result.answer == OUT_OF_SCOPE_ANSWER and not result.grounded and CONTRA_TOOL_NAME not in result.tools_used


def test_build_contra_tool_follows_explicit_path_and_default_location():
    import tempfile
    from pathlib import Path

    from app.llm.v2.contra_index import build_index
    from app.llm.v2.contra_rds import RdsContraStore
    from app.llm.v2.contra_store import ContraStore, ContraStoreError

    tmp = Path(tempfile.mkdtemp())
    settings = make_settings()
    original = agent_module.DEFAULT_CONTRA_DB
    try:
        agent_module.DEFAULT_CONTRA_DB = tmp / "none.sqlite"
        # 기본 위치에 파일이 없으면 RDS(gold.drug_contraindication)를 읽는다
        assert isinstance(agent_module._build_contra_tool(settings, object())._store, RdsContraStore)
        index = tmp / "contra.sqlite"
        build_index([], index)
        agent_module.DEFAULT_CONTRA_DB = index
        assert isinstance(agent_module._build_contra_tool(settings, object())._store, ContraStore)  # 기본 위치에 있으면 SQLite
        with raises(ContraStoreError):  # 경로를 명시했는데 없으면 설정 실수 → 오류
            agent_module._build_contra_tool(make_settings(contra_db_path=str(tmp / "missing.sqlite")), object())
        # 출처를 명시하면 파일 유무와 상관없이 그대로 따른다
        assert isinstance(agent_module._build_contra_tool(make_settings(contra_source="rds"), object())._store, RdsContraStore)
        assert agent_module._build_contra_tool(make_settings(contra_source="off"), object()) is None
        assert isinstance(agent_module._build_contra_tool(make_settings(contra_source="sqlite"), object())._store, ContraStore)
        agent_module.DEFAULT_CONTRA_DB = tmp / "none.sqlite"
        with raises(ContraStoreError):  # sqlite 를 명시했는데 파일이 없으면 오류
            agent_module._build_contra_tool(make_settings(contra_source="sqlite"), object())
    finally:
        agent_module.DEFAULT_CONTRA_DB = original


def test_build_agent_enforces_credential_policy_before_building_anything():
    from app.llm.v2.aws_auth import CredentialPolicyError

    calls = []

    def strict(settings):
        calls.append("auth")
        raise CredentialPolicyError("EC2 인스턴스 역할 자격증명이 필요합니다.")

    original_auth, original_engine = agent_module.ensure_credentials, agent_module.build_engine
    agent_module.ensure_credentials = strict
    agent_module.build_engine = lambda settings: calls.append("engine")  # 도달하면 안 된다
    try:
        with raises(CredentialPolicyError) as caught:
            agent_module.build_agent(make_settings())
    finally:
        agent_module.ensure_credentials, agent_module.build_engine = original_auth, original_engine
    assert calls == ["auth"] and "역할" in str(caught.value)


async def test_answer_entrypoint_reports_error_when_credential_policy_fails():
    from app.llm.v2.aws_auth import CredentialPolicyError

    def strict(settings):
        raise CredentialPolicyError("EC2 인스턴스 역할 자격증명이 필요합니다.")

    original = agent_module.ensure_credentials
    agent_module._agent = None
    agent_module.ensure_credentials = strict
    try:
        result = await answer("타이레놀 복용법", None)
    finally:
        agent_module.ensure_credentials = original
        agent_module._agent = None
    assert result.stop_reason == "error" and result.answer == ERROR_ANSWER  # 서버가 정책을 어기면 답하지 않는다


def test_fixed_no_evidence_messages_explain_what_the_bot_can_do():
    for text in (NO_EVIDENCE_ANSWER, OUT_OF_SCOPE_ANSWER):
        assert "약 이름" in text and "병용 주의사항" in text and "약사나 의사" in text
    assert "등록된 정보에서 확인할 수 없어요" in NO_EVIDENCE_ANSWER  # 없는 제품 시나리오(S10)가 기대하는 문구
    assert "지원하지 않아요" in OUT_OF_SCOPE_ANSWER and "증상" in OUT_OF_SCOPE_ANSWER and "성분" in OUT_OF_SCOPE_ANSWER

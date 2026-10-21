"""모델 비교 테스트: 가짜 모델 두 개를 같은 도구로 돌려 지표·판정을 확인한다."""
from types import SimpleNamespace

from app.llm.v2.agent import AgentAnswer, DrugInfoAgent
from app.llm.v2.config import ConfigError
from app.llm.v2.evaluation.model_compare import compare, format_summary, judge, parse_models, summarize_runs
from app.llm.v2.harness import Limits
from app.llm.v2.tests.helpers import ScriptedModel, raises, response, text_block
from app.llm.v2.tests.test_agent import FOUND, FakeTool, search_call
from app.llm.v2.tools import Evidence


def with_usage(resp, tokens_in, tokens_out):
    resp.usage = SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out)
    return resp


def test_parse_models():
    assert parse_models(["haiku=id-a", "sonnet=id-b"]) == {"haiku": "id-a", "sonnet": "id-b"}
    for bad in (["haiku=id-a"], ["a=1", "a=2"], ["noequals", "b=2"], ["=x", "b=2"]):
        with raises(ConfigError):
            parse_models(bad)


def test_judge():
    case = {"product_name": "타이레놀", "expected_section": "usage"}
    ok = AgentAnswer("a", evidence=[Evidence("타이레놀", "M", "usage", 1)])
    other_product = AgentAnswer("a", evidence=[Evidence("게보린", "M", "usage", 1)])
    shared = AgentAnswer("a", evidence=[Evidence("게보린", "M", "usage", 3)])
    wrong_section = AgentAnswer("a", evidence=[Evidence("타이레놀", "M", "storage", 1)])
    assert judge(ok, case) == {"section_hit": True, "product_hit": True}
    assert judge(other_product, case) == {"section_hit": True, "product_hit": False}
    assert judge(shared, case)["product_hit"] is True
    assert judge(wrong_section, case) == {"section_hit": False, "product_hit": False}
    assert judge(ok, {"question": "q"}) == {"section_hit": None, "product_hit": None}


async def test_compare_runs_same_cases_on_every_model_and_counts_tokens():
    cases = [{"question": "타이레놀 복용법", "product_name": "타이레놀", "expected_section": "usage"}, {"question": "그냥 질문"}]
    fast = ScriptedModel(
        with_usage(response(search_call()), 100, 10), with_usage(response(text_block("답")), 150, 20),
        with_usage(response(text_block("모름")), 50, 5),
    )
    sloppy = ScriptedModel(with_usage(response(text_block("도구 없이 답")), 40, 8), with_usage(response(text_block("모름")), 40, 8))
    agents = {
        "fast": DrugInfoAgent(fast, FakeTool(FOUND), Limits()),
        "sloppy": DrugInfoAgent(sloppy, FakeTool(FOUND), Limits()),
    }
    runs, records = await compare(cases, agents, verbose=False)
    summary = {label: summarize_runs(items) for label, items in runs.items()}
    assert summary["fast"]["grounded_rate"] == 0.5 and summary["sloppy"]["grounded_rate"] == 0.0
    assert summary["fast"]["section_hit_rate"] == 1.0 and summary["sloppy"]["section_hit_rate"] == 0.0
    assert summary["fast"]["judged"] == 1 and summary["fast"]["avg_tool_calls"] == 0.5
    first = runs["fast"][0]["answer"]
    assert (first.input_tokens, first.output_tokens) == (250, 30)  # 라운드 합산
    assert records[0]["models"]["sloppy"]["stop_reason"] == "no_evidence"
    assert set(records[0]["models"]) == {"fast", "sloppy"}
    table = format_summary(summary)
    assert "fast" in table and "sloppy" in table and "근거 기반 답변 비율" in table


def test_summarize_empty():
    assert summarize_runs([])["questions"] == 0

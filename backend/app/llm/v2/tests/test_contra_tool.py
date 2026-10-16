"""check_contraindication 도구 테스트: 가짜 검색 DB + 합성 병용금기 인덱스."""
import datetime
import tempfile
from pathlib import Path

from app.llm.v2.contra_index import build_index
from app.llm.v2.contra_store import ContraStore
from app.llm.v2.contra_tool import CONTRA_TOOL_NAME, ContraindicationTool, build_contra_spec
from app.llm.v2.tests.helpers import FakeReader, FakeReaderFactory, make_settings

CATALOG = [
    {"product_key": "drug:100", "product_name": "와파린정", "manufacturer": "A사", "product_type": "drug"},
    {"product_key": "drug:200", "product_name": "아스피린장용정100밀리그램", "manufacturer": "B사", "product_type": "drug"},
    {"product_key": "drug:300", "product_name": "타이레놀정500밀리그램", "manufacturer": "C사", "product_type": "drug"},
    {"product_key": "drug:310", "product_name": "타이레놀8시간정", "manufacturer": "C사", "product_type": "drug"},
    {"product_key": "drug:400", "product_name": "수출용약(수출명:EXPORT)", "manufacturer": "D사", "product_type": "drug"},
    {"product_key": "health_food:9", "product_name": "홍삼정", "manufacturer": "E사", "product_type": "health_food"},
]


def _row(a, b, content="출혈 위험 증가", remark=None, ingr=("와파린",), mix=("아스피린",), dur="1"):
    return {
        "level": "품목", "item_seq": a, "mixture_item_seq": b, "ingr_names": list(ingr), "mixture_ingr_names": list(mix),
        "prohbt_content": content, "remark": remark, "form_name": "정제", "dur_seq": dur,
        "notification_date": datetime.date(2012, 3, 2), "snapshot": datetime.date(2026, 10, 13),
    }


def _store(rows):
    path = Path(tempfile.mkdtemp()) / "contra.sqlite"
    build_index(rows, path)
    return ContraStore(path)


def _db(sql, params):
    if "active_snapshot" in sql:
        return [{"run_id": "run1"}]
    if "SELECT DISTINCT product_key" in sql:
        if "product_key = :product_key" in sql:
            return [p for p in CATALOG if p["product_key"] == params["product_key"]]
        value = params["value"]
        if "= :value" in sql:
            return [p for p in CATALOG if p["product_name"].lower() == value]
        if value.startswith("%"):
            return [p for p in CATALOG if value.strip("%") in p["product_name"].lower()]
        return [p for p in CATALOG if p["product_name"].lower().startswith(value.rstrip("%"))]
    raise AssertionError(f"예상하지 못한 SQL: {sql[:60]}")


def _tool(rows, db=_db):
    reader = FakeReader(db)
    return ContraindicationTool(make_settings(), FakeReaderFactory(reader), _store(rows)), reader


async def test_pair_with_rule_reports_content_conditions_and_evidence():
    tool, _ = _tool([_row("200", "100", remark="48시간 이내 병용금기", ingr=("아스피린",), mix=("와파린",))])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert not result.is_error
    assert "[병용금기 확인 | 자료 기준일 2026-10-13 | 확인한 제품 2개]" in result.text
    assert "[출처 | 와파린정 × 아스피린장용정100밀리그램 | 병용금기(DUR)]" in result.text
    assert "성분: 와파린 × 아스피린" in result.text  # 질문 순서(와파린이 앞)에 맞게 성분 방향이 정렬된다
    assert "금기 내용: 출혈 위험 증가" in result.text and "조건·비고: 48시간 이내 병용금기" in result.text
    assert "고시일: 2012-03-02" in result.text
    assert [e.label for e in result.evidence] == ["와파린정 × 아스피린장용정100밀리그램 · 병용금기(DUR)"]


async def test_pair_without_rule_never_says_safe():
    tool, _ = _tool([_row("100", "200")])
    result = await tool.run({"products": ["와파린정", "타이레놀정500밀리그램"]})
    assert "병용금기 규칙 없음" in result.text and "안전하다는 뜻이 아닙니다" in result.text
    assert "타이레놀정500밀리그램" in result.text.split("이 자료에 병용금기 규칙이 하나도 등록돼 있지 않은 제품:")[1]
    assert [e.section_type for e in result.evidence] == ["contraindication_none"]
    assert result.evidence[0].label.endswith("병용금기 자료 조회(해당 규칙 없음)")


async def test_three_products_check_every_pair():
    tool, _ = _tool([_row("100", "200"), _row("100", "300", content="다른 사유")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램", "타이레놀정500밀리그램"]})
    assert result.text.count("■ ") == 3 and "금기 내용: 다른 사유" in result.text
    assert sorted(e.section_type for e in result.evidence) == ["contraindication", "contraindication", "contraindication_none"]


async def test_ambiguous_name_asks_instead_of_choosing_and_skips_lookup():
    tool, _ = _tool([_row("100", "300")])
    result = await tool.run({"products": ["와파린정", "타이레놀"]})
    assert result.text.startswith("[확인 필요]") and "product_key=drug:300" in result.text and "product_key=drug:310" in result.text
    assert result.evidence == [] and {c["product_key"] for c in result.candidates} == {"drug:300", "drug:310"}


async def test_product_key_input_resolves_directly():
    tool, reader = _tool([_row("100", "310")])
    result = await tool.run({"products": ["drug:100", "ｄｒｕｇ:310"]})  # 전각 문자도 NFKC 로 정리
    assert "병용금기 규칙 있음" in result.text and "타이레놀8시간정" in result.text
    assert all("lower(product_name)" not in sql for sql, _ in reader.calls)  # 이름 검색은 하지 않았다


async def test_not_found_health_food_and_unknown_key():
    tool, _ = _tool([_row("100", "200")])
    missing = await tool.run({"products": ["와파린정", "없는약"]})
    assert missing.text.startswith("[검색 결과 없음]") and "없는약" in missing.text and missing.evidence == []
    food = await tool.run({"products": ["와파린정", "health_food:9"]})
    assert food.text.startswith("[확인 불가]") and food.evidence == []
    unknown = await tool.run({"products": ["와파린정", "drug:999999"]})
    assert unknown.text.startswith("[검색 결과 없음]")


async def test_argument_validation_does_not_touch_db():
    tool, reader = _tool([_row("100", "200")])
    for bad in (
        None, {}, {"products": "와파린정"}, {"products": ["와파린정"]}, {"products": ["와파린정", "와파린정"]},
        {"products": ["a", "b", "c", "d", "e", "f"]}, {"products": ["와파린정", 5]}, {"products": ["와파린정", "가" * 101]},
    ):
        result = await tool.run(bad)
        assert result.is_error and result.text.startswith("[인자 오류]"), bad
    assert reader.calls == []


async def test_same_product_resolved_twice_is_an_error():
    tool, _ = _tool([_row("100", "200")])
    result = await tool.run({"products": ["와파린정", "drug:100"]})
    assert result.is_error and result.text.startswith("[인자 오류]")


async def test_approximate_name_is_flagged():
    tool, _ = _tool([_row("100", "400")])
    result = await tool.run({"products": ["와파린정", "수출용약(다른표기)"]})
    assert result.text.startswith("[참고] '수출용약(다른표기)'과(와) 정확히 일치하는 제품이 없어")
    assert "수출용약" in result.text and "(수출명:EXPORT)" not in result.text.split("[출처")[1]  # 표시용 이름은 줄인다


async def test_many_rules_are_capped_and_duplicates_collapse():
    rows = [_row("100", "200", content=f"사유{i}", dur=str(i)) for i in range(8)] + [_row("100", "200", content="사유0", dur="99")]
    tool, _ = _tool(rows)
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert result.text.count("금기 내용:") == 5 and "같은 조합의 규칙이 3건 더 있습니다" in result.text


async def test_internal_errors_are_hidden():
    tool, _ = _tool([_row("100", "200")])

    def broken(*args, **kwargs):
        raise RuntimeError("secret path /home/x/contra.sqlite")

    tool._store.lookup = broken
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert result.is_error and result.text == "[검색 오류] 지금은 병용금기 정보를 조회할 수 없습니다." and "secret" not in result.text


def test_spec_shape():
    spec = build_contra_spec()
    assert spec["name"] == CONTRA_TOOL_NAME == "check_contraindication"
    products = spec["input_schema"]["properties"]["products"]
    assert products["minItems"] == 2 and products["maxItems"] == 5 and spec["input_schema"]["required"] == ["products"]


# --------------------------------------------------------------------------- 평가 코드

def test_outcome_of_classifies_tool_results():
    from app.llm.v2.evaluation.contra_eval import outcome_of
    from app.llm.v2.tools import Evidence, ToolResult

    assert outcome_of(ToolResult("[확인 필요] ...")) == "clarify"
    assert outcome_of(ToolResult("[검색 결과 없음] ...")) == "not_found" and outcome_of(ToolResult("[확인 불가] ...")) == "not_found"
    assert outcome_of(ToolResult("x", [Evidence("a", "", "contraindication", 1)])) == "found"
    assert outcome_of(ToolResult("x", [Evidence("a", "", "contraindication_none", 1)])) == "none"
    assert outcome_of(ToolResult("x", [Evidence("a", "", "contraindication", 1), Evidence("b", "", "contraindication_none", 1)])) == "found"
    assert outcome_of(ToolResult("x")) == "other"


def test_make_negatives_excludes_positives_and_is_reproducible():
    from app.llm.v2.evaluation.contra_eval import make_negatives

    keys = ["1", "2", "3", "4"]
    positives = {("1", "2"), ("3", "4")}
    first = make_negatives(keys, positives, 3)
    assert first == make_negatives(keys, positives, 3) and len(first) == 3
    assert all(pair not in positives and pair[0] < pair[1] for pair in first)
    assert make_negatives(["1"], set(), 3) == []


async def test_evaluate_pairs_counts_by_key_and_by_name():
    from app.llm.v2.evaluation.contra_eval import evaluate_pairs, format_report
    from app.llm.v2.tools import Evidence, ToolResult

    names = {"1": "가정", "2": "나정", "3": "다정"}

    async def run_tool(products):
        by_key = products[0].startswith("drug:")
        pair = tuple(sorted(p.removeprefix("drug:") if by_key else {"가정": "1", "나정": "2", "다정": "3"}[p] for p in products))
        if not by_key and pair == ("1", "3"):
            return ToolResult("[확인 필요] ...")  # 이름으로는 되묻기
        kind = "contraindication" if pair == ("1", "2") else "contraindication_none"
        return ToolResult("x", [Evidence("a", "", kind, 1)])

    report = await evaluate_pairs([("1", "2")], [("1", "3"), ("2", "3")], names, run_tool)
    assert report["counts"]["positive/key"] == {"found": 1} and report["counts"]["positive/name"] == {"found": 1}
    assert report["counts"]["negative/key"] == {"none": 2} and report["counts"]["negative/name"] == {"none": 1, "clarify": 1}
    assert report["problems"] == []
    assert "기대(none)" in format_report(report) and "negative 에서 found" in format_report(report)
    broken = await evaluate_pairs([("1", "3")], [], names, run_tool)  # 키로는 규칙 없음(none) → 양성인데 놓침
    assert broken["problems"] and broken["problems"][0].startswith("[positive/key→none]")


def test_contra_prompt_forbids_unsourced_stop_or_continue_advice():
    from app.llm.v2.prompts import CONTRA_PROMPT_ADDENDUM

    assert "이미 함께 쓰고 있다고 해도 중단하라거나 계속하라는 말은 하지 않고" in CONTRA_PROMPT_ADDENDUM
    assert "안전하다, 괜찮다, 문제없다고 말하지 않고" in CONTRA_PROMPT_ADDENDUM

"""RDS 병용금기 저장소(RdsContraStore)와, 이를 쓰는 check_contraindication 도구 테스트: 가짜 Reader 로 SQL 을 흉내 낸다."""
import datetime

from app.llm.v2.contra_rds import RdsContraStore
from app.llm.v2.contra_tool import ContraindicationTool
from app.llm.v2.tests.helpers import FakeReader, FakeReaderFactory, make_settings
from app.llm.v2.tests.test_contra_tool import CATALOG, _db


def _rule(a, b, content="출혈 위험 증가", remark=None, ingr=("와파린",), mix=("아스피린",), basis="품목 DUR", date=datetime.date(2012, 3, 2)):
    return {
        "item_seq": a, "mixture_item_seq": b, "ingr_names": list(ingr), "mixture_ingr_names": list(mix),
        "prohbt_content": content, "remark": remark, "notification_date": date, "basis": basis,
    }


def _rds_handler(rules, base=_db):
    """gold.drug_contraindication 에 대한 SELECT 를 rules 리스트로 흉내 낸다. 그 밖의 SQL 은 base 로 넘긴다."""

    def handler(sql, params):
        if "gold.drug_contraindication" not in sql:
            return base(sql, params)
        if "WHERE item_seq = :seq" in sql:
            return [{"hit": 1}] if any(r["item_seq"] == params["seq"] for r in rules) else []
        assert "item_seq = :first AND mixture_item_seq = :second" in sql
        found = [r for r in rules if r["item_seq"] == params["first"] and r["mixture_item_seq"] == params["second"]]
        found.sort(key=lambda r: 0 if r["basis"] == "품목 DUR" else 1)
        return found[: params["limit"]]

    return handler


def _tool(rules):
    reader = FakeReader(_rds_handler(rules))
    return ContraindicationTool(make_settings(), FakeReaderFactory(reader), RdsContraStore()), reader


async def test_forward_direction_is_enough_when_both_directions_are_stored():
    rules = [_rule("100", "200"), _rule("200", "100", ingr=("아스피린",), mix=("와파린",))]
    tool, reader = _tool(rules)
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert not result.is_error
    assert "자료 기준일" not in result.text  # 이 테이블에는 적재 기준일이 없어 적지 않는다
    assert "[병용금기 확인 | 확인한 제품 2개]" in result.text
    assert "[출처 | 와파린정 × 아스피린장용정100밀리그램 | 병용금기(DUR)]" in result.text
    assert "성분: 와파린 × 아스피린" in result.text and "금기 내용: 출혈 위험 증가" in result.text
    assert "고시일: 2012-03-02" in result.text and "규칙 종류: 품목 DUR" in result.text
    pair_queries = [p for sql, p in reader.calls if "mixture_item_seq = :second" in sql]
    assert pair_queries == [{"first": "100", "second": "200", "limit": 20}]  # 정방향에서 찾았으면 반대 방향은 조회하지 않는다


async def test_reverse_direction_is_used_when_only_one_side_is_stored_and_names_follow_question_order():
    tool, reader = _tool([_rule("200", "100", ingr=("아스피린",), mix=("와파린",), content="역방향만 저장")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert "금기 내용: 역방향만 저장" in result.text
    assert "성분: 와파린 × 아스피린" in result.text  # 질문에서 앞에 놓은 제품 쪽 성분이 앞에 온다
    assert len([1 for sql, _ in reader.calls if "mixture_item_seq = :second" in sql]) == 2


async def test_ingredient_rules_are_labeled_and_product_dur_comes_first_and_duplicates_collapse():
    rules = [
        _rule("100", "200", content="성분 단위 사유", basis="성분 규칙"),
        _rule("100", "200", content="출혈 위험 증가", basis="품목 DUR"),
        _rule("100", "200", content="출혈 위험 증가", basis="성분 규칙"),  # 내용이 같으면 한 번만
    ]
    tool, _ = _tool(rules)
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    text = result.text
    assert text.count("금기 내용:") == 2
    assert text.index("출혈 위험 증가") < text.index("성분 단위 사유")
    assert "규칙 종류: 성분 규칙" in text and "규칙 종류: 품목 DUR" in text


async def test_no_rule_never_says_safe_and_reports_products_missing_from_the_data():
    tool, _ = _tool([_rule("100", "300")])  # 와파린은 자료에 있고 아스피린(200)은 어떤 규칙에도 없다
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert "병용금기 규칙 없음" in result.text and "안전하다는 뜻이 아닙니다" in result.text
    assert "규칙이 하나도 등록돼 있지 않은 제품: 아스피린장용정100밀리그램" in result.text
    assert [e.section_type for e in result.evidence] == ["contraindication_none"]


async def test_three_drugs_query_every_pair_and_remark_and_empty_values_are_handled():
    rules = [
        _rule("100", "200", remark="48시간 이내", date=None),
        _rule("200", "300", content=None, basis=None, ingr=(), mix=("타이레놀",)),
    ]
    tool, reader = _tool(rules)
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램", "타이레놀정500밀리그램"]})
    assert result.text.count("■ ") == 3
    assert "조건·비고: 48시간 이내" in result.text and "고시일" not in result.text.split("■ ")[1]
    assert "(원문에 금기 내용이 비어 있습니다)" in result.text and "성분: (미상) × 타이레놀" in result.text
    assert len([1 for sql, _ in reader.calls if "WHERE item_seq = :seq" in sql]) == 3


async def test_queries_are_select_only_with_bound_parameters():
    tool, reader = _tool([_rule("100", "200")])
    await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    gold = [(sql, params) for sql, params in reader.calls if "gold.drug_contraindication" in sql]
    assert gold and all(sql.lstrip().upper().startswith("SELECT") for sql, _ in gold)
    assert all("100" not in sql and "200" not in sql for sql, _ in gold)  # 값은 SQL 문자열에 섞이지 않고 파라미터로만 간다


async def test_database_errors_are_hidden():
    def broken(sql, params):
        if "gold.drug_contraindication" in sql:
            raise RuntimeError("relation gold.drug_contraindication password=secret")
        return _db(sql, params)

    tool = ContraindicationTool(make_settings(), FakeReaderFactory(FakeReader(broken)), RdsContraStore())
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert result.is_error and result.text == "[검색 오류] 지금은 병용금기 정보를 조회할 수 없습니다." and "secret" not in result.text


async def test_health_food_combination_does_not_touch_the_rule_table():
    tool, reader = _tool([_rule("100", "200")])
    result = await tool.run({"products": ["와파린정", "홍삼정"]})
    assert not result.is_error and "병용금기 판정 불가" in result.text
    assert not any("gold.drug_contraindication" in sql for sql, _ in reader.calls)

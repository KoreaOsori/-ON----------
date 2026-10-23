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


def _rds_handler(rules, base=_db, codes=None, ingredient_rules=(), overlap_rules=(), routes=None, overlap_error=False):
    """gold.drug_contraindication 에 대한 SELECT 를 rules 리스트로 흉내 낸다. 그 밖의 SQL 은 base 로 넘긴다.

    codes: item_seq → DUR 성분 코드 목록(gold.drug_ingredient). 없으면 성분 코드를 모르는 제품으로 본다.
    ingredient_rules: 성분 코드 조합 규칙 [(코드, 상대 코드, 금기 내용, 비고, 앞 성분명, 뒤 성분명)] — 품목 병용금기가 없을 때의 성분 비교용."""
    codes = codes or {}
    routes = routes or {}

    def handler(sql, params):
        if "gold.drug WHERE" in sql:
            if overlap_error:
                raise RuntimeError("boom")
            return [{"item_seq": seq, "route": routes.get(seq)} for seq in params["seqs"]]
        if "gold.dur_ingredient_rule" in sql:
            return [{"sers_name": ser, "ingr_code": code, "ingr_name": name} for ser, code, name in overlap_rules if code in params["codes"]]
        if "gold.drug_ingredient" in sql and "item_seq = :seq" in sql:
            return [{"dur_ingr_code": c} for c in codes.get(params["seq"], [])]
        if "ANY(:first_codes)" in sql:
            return [
                {"first_name": a, "second_name": b, "prohbt_content": content, "remark": remark, "basis": "품목 DUR", "notification_date": None}
                for code, mix, content, remark, a, b in ingredient_rules
                if code in params["first_codes"] and mix in params["second_codes"]
            ]
        if "gold.drug_contraindication" not in sql:
            return base(sql, params)
        if "WHERE item_seq = :seq" in sql:
            return [{"hit": 1}] if any(r["item_seq"] == params["seq"] for r in rules) else []
        assert "item_seq = :first AND mixture_item_seq = :second" in sql
        found = [r for r in rules if r["item_seq"] == params["first"] and r["mixture_item_seq"] == params["second"]]
        found.sort(key=lambda r: 0 if r["basis"] == "품목 DUR" else 1)
        return found[: params["limit"]]

    return handler


def _tool(rules, **kwargs):
    reader = FakeReader(_rds_handler(rules, **kwargs))
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


async def test_ingredient_only_pair_is_reported_as_ingredient_level_caution_not_contraindication():
    tool, _ = _tool([_rule("100", "200", content="심실성빈맥", basis="성분 규칙")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    text = result.text
    assert "성분 기준 주의 규칙 있음(품목 단위 병용금기는 아님)" in text
    assert "[출처 | 와파린정 × 아스피린장용정100밀리그램 | 병용 주의(성분 기준)]" in text
    assert "금기 내용: 심실성빈맥" in text and "규칙 종류: 성분 규칙" in text
    assert "'병용금기'라고 단정하지 말고" in text
    assert "병용금기 규칙 있음" not in text
    assert [e.section_type for e in result.evidence] == ["contraindication_ingredient"]
    assert [e.label for e in result.evidence] == ["와파린정 × 아스피린장용정100밀리그램 · 병용 주의(성분 기준)"]


async def test_pair_with_product_dur_stays_contraindication_even_if_ingredient_rules_exist_too():
    tool, _ = _tool([_rule("100", "200", basis="성분 규칙", content="성분 단위"), _rule("100", "200", basis="품목 DUR")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert "병용금기 규칙 있음" in result.text and "성분 기준 주의" not in result.text
    assert [e.section_type for e in result.evidence] == ["contraindication"]


async def test_mixed_pairs_are_labeled_per_pair():
    tool, _ = _tool([_rule("100", "200", basis="품목 DUR"), _rule("100", "300", basis="성분 규칙", content="성분 단위")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램", "타이레놀정500밀리그램"]})
    assert sorted(e.section_type for e in result.evidence) == ["contraindication", "contraindication_ingredient", "contraindication_none"]


def test_prompt_and_outcome_know_ingredient_level_caution():
    from app.llm.v2.evaluation.contra_eval import outcome_of
    from app.llm.v2.prompts import CONTRA_PROMPT_ADDENDUM
    from app.llm.v2.tools import Evidence, ToolResult

    assert "성분 기준 주의 규칙 있음" in CONTRA_PROMPT_ADDENDUM and "'병용금기'라고 하지 말고" in CONTRA_PROMPT_ADDENDUM
    assert outcome_of(ToolResult("x", [Evidence("a", "", "contraindication_ingredient", 1)])) == "found"


async def test_product_dur_present_shows_only_product_dur_and_never_compares_ingredients():
    rules = [
        _rule("100", "200", content="성분 단위 사유", basis="성분 규칙"),
        _rule("100", "200", content="출혈 위험 증가", basis="품목 DUR"),
    ]
    tool, reader = _tool(rules, codes={"100": ["D1"], "200": ["D2"]}, ingredient_rules=[("D1", "D2", "성분 비교 사유", None, "와파린", "아스피린")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    text = result.text
    assert "병용금기 규칙 있음" in text and "성분 기준 주의" not in text
    assert text.count("금기 내용:") == 1 and "출혈 위험 증가" in text
    assert "성분 단위 사유" not in text and "성분 비교 사유" not in text and "[성분 기준 조회]" not in text
    assert not any("ANY(:first_codes)" in sql for sql, _ in reader.calls)  # 성분 비교 쿼리는 아예 나가지 않는다
    assert [e.section_type for e in result.evidence] == ["contraindication"]


async def test_without_product_dur_ingredients_are_compared_and_reported_as_ingredient_caution():
    tool, reader = _tool(
        [], codes={"100": ["D1"], "200": ["D2", "D3"]},
        ingredient_rules=[("D1", "D3", "심실성빈맥", "고용량", "와파린", "아스피린"), ("D9", "D8", "관계없음", None, "가", "나")],
    )
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    text = result.text
    assert "성분 기준 주의 규칙 있음(품목 단위 병용금기는 아님)" in text and "[성분 기준 조회]" in text
    assert "성분: 와파린 × 아스피린" in text and "금기 내용: 심실성빈맥" in text and "조건·비고: 고용량" in text
    assert "규칙 종류: 성분 규칙" in text and "규칙 종류: 품목 DUR" not in text  # 성분 단위 조회에서 나온 품목 DUR 행도 성분 규칙으로 표시
    assert "병용금기 규칙 있음" not in text and "관계없음" not in text
    assert [e.section_type for e in result.evidence] == ["contraindication_ingredient"]
    calls = [p for sql, p in reader.calls if "ANY(:first_codes)" in sql]
    assert calls[0] == {"first_codes": ["D1"], "second_codes": ["D2", "D3"], "limit": 20}


async def test_ingredient_comparison_reads_reverse_direction_and_keeps_question_order():
    tool, _ = _tool([], codes={"100": ["D1"], "200": ["D2"]}, ingredient_rules=[("D2", "D1", "역방향 사유", None, "아스피린", "와파린")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert "성분: 와파린 × 아스피린" in result.text and "역방향 사유" in result.text


async def test_ingredient_rules_already_expanded_in_product_table_are_merged_without_duplicates():
    rules = [_rule("100", "200", content="출혈 위험 증가", basis="성분 규칙")]
    tool, _ = _tool(
        rules, codes={"100": ["D1"], "200": ["D2"]},
        ingredient_rules=[("D1", "D2", "출혈 위험 증가", None, "와파린", "아스피린"), ("D1", "D2", "추가 사유", None, "와파린", "아스피린")],
    )
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert result.text.count("금기 내용:") == 2
    assert "추가 사유" in result.text and "규칙 종류: 품목 DUR" not in result.text


async def test_missing_ingredient_codes_do_not_turn_a_product_pair_into_unknown_and_keep_product_level_none():
    tool, reader = _tool([], codes={"100": ["D1"]}, ingredient_rules=[("D1", "D2", "x", None, "a", "b")])
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})  # 아스피린 쪽 성분 코드를 모른다
    assert "병용금기 규칙 없음" in result.text and "안전하다는 뜻이 아닙니다" in result.text and "[확인 불가]" not in result.text
    assert not any("ANY(:first_codes)" in sql for sql, _ in reader.calls)
    assert [e.section_type for e in result.evidence] == ["contraindication_none"]


async def test_three_products_compare_ingredients_only_for_pairs_without_product_dur():
    tool, _ = _tool(
        [_rule("100", "200")], codes={"100": ["D1"], "200": ["D2"], "300": ["D3"]},
        ingredient_rules=[("D1", "D3", "성분 사유", None, "와파린", "아세트아미노펜")],
    )
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램", "타이레놀정500밀리그램"]})
    assert sorted(e.section_type for e in result.evidence) == ["contraindication", "contraindication_ingredient", "contraindication_none"]
    assert result.text.count("[성분 기준 조회]") == 1


async def test_no_rule_text_says_ingredients_were_compared_or_could_not_be():
    tool, _ = _tool([], codes={"100": ["D1"], "200": ["D2"]})
    text = (await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})).text
    assert "품목 단위와 성분(DUR 성분 코드) 기준 모두 비교했습니다" in text and "안전하다는 뜻이 아닙니다" in text
    tool, _ = _tool([], codes={"100": ["D1"]})
    text = (await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})).text
    assert "성분 기준 비교는 하지 못했고 품목 단위로만 확인했습니다" in text


OVERLAP = [("비스테로이드성 소염제", "D1", "이부프로펜"), ("비스테로이드성 소염제", "D2", "덱시부프로펜"), ("항히스타민제", "D3", "히드록시진")]


async def test_efficacy_overlap_is_reported_next_to_contraindication_result():
    tool, reader = _tool([], codes={"100": ["D1"], "200": ["D2"]}, overlap_rules=OVERLAP)
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    text = result.text
    assert "병용금기 규칙 없음" in text and "효능군 중복 주의 규칙 있음(병용금기는 아님)" in text
    assert "같은 계열: 비스테로이드성 소염제" in text and "와파린정(이부프로펜), 아스피린장용정100밀리그램(덱시부프로펜)" in text
    assert "'병용금기'라고 하지 말고" in text
    assert [e.section_type for e in result.evidence] == ["contraindication_none", "efficacy_overlap"]
    assert result.evidence[1].label == "와파린정 × 아스피린장용정100밀리그램 · 효능군 중복 주의(성분 기준)"
    assert any("gold.dur_ingredient_rule" in sql and "mix_type = '단일'" in sql for sql, _ in reader.calls)


async def test_overlap_needs_different_ingredients_from_different_products():
    # 같은 성분(D1)만 두 제품에 있으면 효능군 '서로 다른 성분' 중복이 아니다
    tool, _ = _tool([], codes={"100": ["D1"], "200": ["D1"]}, overlap_rules=OVERLAP)
    assert "효능군 중복" not in (await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})).text
    # 한 제품 안에 두 성분이 모두 있고 다른 제품에는 계열이 없으면 중복이 아니다
    tool, _ = _tool([], codes={"100": ["D1", "D2"], "200": ["D9"]}, overlap_rules=OVERLAP)
    assert "효능군 중복" not in (await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})).text
    # 다른 계열이면 해당 없음
    tool, _ = _tool([], codes={"100": ["D1"], "200": ["D3"]}, overlap_rules=OVERLAP)
    assert "효능군 중복" not in (await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})).text


async def test_non_oral_products_are_left_out_of_the_overlap_check():
    tool, _ = _tool([], codes={"100": ["D1"], "200": ["D2"]}, overlap_rules=OVERLAP, routes={"200": "경구 외"})
    assert "효능군 중복" not in (await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})).text


async def test_overlap_failure_never_breaks_the_contraindication_answer():
    tool, _ = _tool([_rule("100", "200")], codes={"100": ["D1"], "200": ["D2"]}, overlap_rules=OVERLAP, overlap_error=True)
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램"]})
    assert not result.is_error and "병용금기 규칙 있음" in result.text and "효능군 중복" not in result.text


async def test_overlap_works_with_a_contraindication_found_and_with_three_products():
    tool, _ = _tool([_rule("100", "300")], codes={"100": ["D1"], "200": ["D3"], "300": ["D2"]}, overlap_rules=OVERLAP)
    result = await tool.run({"products": ["와파린정", "아스피린장용정100밀리그램", "타이레놀정500밀리그램"]})
    assert sorted(e.section_type for e in result.evidence) == ["contraindication", "contraindication_none", "contraindication_none", "efficacy_overlap"]
    assert "와파린정 × 타이레놀정500밀리그램 · 효능군 중복 주의(성분 기준)" in [e.label for e in result.evidence]


def test_outcome_ignores_efficacy_overlap():
    from app.llm.v2.evaluation.contra_eval import outcome_of
    from app.llm.v2.tools import Evidence, ToolResult

    assert outcome_of(ToolResult("x", [Evidence("a", "", "contraindication_none", 1), Evidence("b", "", "efficacy_overlap", 1)])) == "none"


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
    assert len([1 for sql, _ in reader.calls if "WHERE item_seq = :seq" in sql and "gold.drug_contraindication" in sql]) == 3


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


# ----------------------------------------------------------------------------- 성분 이름 / 성분 코드 조회

# 제품별 성분(gold.drug_ingredient): item_seq → DUR 성분 코드
DRUG_INGREDIENTS = [
    {"item_seq": "100", "ingr_name": "와파린나트륨", "dur_ingr_code": "D000001"},
    {"item_seq": "200", "ingr_name": "아스피린", "dur_ingr_code": "D000002"},
    {"item_seq": "300", "ingr_name": "아세트아미노펜", "dur_ingr_code": "D000147"},
    {"item_seq": "310", "ingr_name": "코드없는원료", "dur_ingr_code": None},
]
# 성분 이름 → 코드 (제품과 연결되지 않은 이름도 있을 수 있어 별도 목록 + 위 목록 모두에서 찾는다)
INGREDIENT_NAMES = DRUG_INGREDIENTS + [
    {"item_seq": "999", "ingr_name": "케토코나졸", "dur_ingr_code": "D000769"},
    {"item_seq": "999", "ingr_name": "트리아졸람", "dur_ingr_code": "D000592"},
    {"item_seq": "998", "ingr_name": "이름만있는성분", "dur_ingr_code": None},
]


def _crow(code, mix_code, content="출혈 위험 증가", remark=None, basis="품목 DUR", names=("와파린", "아스피린"), date=datetime.date(2012, 3, 2)):
    return {
        "ingr_code": code, "mixture_ingr_code": mix_code, "ingr_names": [names[0]], "mixture_ingr_names": [names[1]],
        "prohbt_content": content, "remark": remark, "notification_date": date, "basis": basis,
        "item_seq": "x", "mixture_item_seq": "y",
    }


def _ingredient_handler(rows, base=_db):
    def handler(sql, params):
        if "gold.drug WHERE" in sql or "gold.dur_ingredient_rule" in sql:  # 효능군 중복 조회는 이 테스트들의 관심사가 아니다
            return []
        if "gold.drug_ingredient" in sql:
            if "WHERE ingr_name = :name" in sql:
                return [{"ingr_name": r["ingr_name"], "dur_ingr_code": r["dur_ingr_code"]} for r in INGREDIENT_NAMES if r["ingr_name"] == params["name"]]
            assert "item_seq = :seq" in sql
            return [{"dur_ingr_code": r["dur_ingr_code"]} for r in DRUG_INGREDIENTS if r["item_seq"] == params["seq"] and r["dur_ingr_code"]]
        if "gold.drug_contraindication" in sql and "ANY(:codes)" in sql:
            return [{"hit": 1}] if any(r["ingr_code"] in params["codes"] for r in rows) else []
        if "ANY(:first_codes)" in sql:
            groups: dict[tuple, dict] = {}
            for r in rows:
                if r["ingr_code"] in params["first_codes"] and r["mixture_ingr_code"] in params["second_codes"]:
                    key = (r["ingr_code"], r["mixture_ingr_code"], r["prohbt_content"], r["remark"], r["basis"])
                    groups.setdefault(key, {"first_name": r["ingr_names"][0], "second_name": r["mixture_ingr_names"][0],
                                            "prohbt_content": r["prohbt_content"], "remark": r["remark"], "basis": r["basis"],
                                            "notification_date": r["notification_date"]})
            return list(groups.values())[: params["limit"]]
        if "gold.drug_contraindication" in sql:  # 제품 쌍 조회/보유 확인은 이 테스트에서 쓰지 않는 길
            return []
        return base(sql, params)

    return handler


def _ingredient_tool(rows):
    reader = FakeReader(_ingredient_handler(rows))
    return ContraindicationTool(make_settings(), FakeReaderFactory(reader), RdsContraStore()), reader


async def test_ingredient_name_is_used_when_no_product_matches_and_result_carries_the_caveat():
    tool, reader = _ingredient_tool([_crow("D000001", "D000147", content="출혈 위험 증가", remark="고용량 병용 시", names=("와파린", "아세트아미노펜"))])
    result = await tool.run({"products": ["와파린정", "아세트아미노펜"]})
    text = result.text
    assert not result.is_error
    assert "[참고] '아세트아미노펜'은(는) 정확히 일치하는 제품명이 없고 성분 이름과 일치해 성분 이름으로 확인했습니다" in text
    assert "[성분 기준 조회]" in text and "제형 등 제품별 조건은 반영되지 않았고" in text
    assert "■ 와파린정 × 아세트아미노펜(성분) — 병용금기 규칙 있음" in text
    assert "금기 내용: 출혈 위험 증가" in text and "조건·비고: 고용량 병용 시" in text and "규칙 종류: 품목 DUR" in text
    assert [e.section_type for e in result.evidence] == ["contraindication"]
    pair_calls = [p for sql, p in reader.calls if "ANY(:first_codes)" in sql]
    assert pair_calls == [{"first_codes": ["D000001"], "second_codes": ["D000147"], "limit": 20}]  # 제품 쪽 코드는 drug_ingredient 에서 가져온다


async def test_two_ingredients_check_the_code_pair_and_ingredient_only_rules_stay_caution():
    rows = [_crow("D000769", "D000592", content="작용 증가", basis="성분 규칙", names=("케토코나졸", "트리아졸람"))]
    tool, _ = _ingredient_tool(rows)
    result = await tool.run({"products": ["케토코나졸", "트리아졸람"]})
    assert "성분 기준 주의 규칙 있음(품목 단위 병용금기는 아님)" in result.text and "[성분 기준 조회]" in result.text
    assert [e.section_type for e in result.evidence] == ["contraindication_ingredient"]


async def test_ingredient_pair_reads_the_reverse_direction_when_only_that_is_stored_and_flips_names():
    tool, _ = _ingredient_tool([_crow("D000592", "D000769", content="작용 증가", names=("트리아졸람", "케토코나졸"))])
    result = await tool.run({"products": ["케토코나졸", "트리아졸람"]})
    assert "성분: 케토코나졸 × 트리아졸람" in result.text  # 질문에서 앞에 놓은 성분이 앞에 온다


async def test_ingredient_pair_without_rule_is_not_called_safe_and_still_has_the_caveat():
    tool, _ = _ingredient_tool([_crow("D000769", "D000592", names=("케토코나졸", "트리아졸람"))])
    result = await tool.run({"products": ["아세트아미노펜", "트리아졸람"]})
    assert "병용금기 규칙 없음" in result.text and "안전하다는 뜻이 아닙니다" in result.text and "[성분 기준 조회]" in result.text
    assert [e.section_type for e in result.evidence] == ["contraindication_none"]


async def test_unknown_names_and_ingredients_without_dur_code_are_reported_not_guessed():
    tool, _ = _ingredient_tool([])
    result = await tool.run({"products": ["와파린정", "없는성분"]})
    assert result.text.startswith("[검색 결과 없음]") and "없는성분" in result.text
    result = await tool.run({"products": ["와파린정", "이름만있는성분"]})
    assert result.text.startswith("[확인 불가]") and "DUR 성분 코드가 없어" in result.text


async def test_drug_without_ingredient_code_is_marked_unresolved_instead_of_no_rule():
    tool, _ = _ingredient_tool([_crow("D000001", "D000147")])
    result = await tool.run({"products": ["와파린정", "아세트아미노펜", "타이레놀8시간정"]})
    text = result.text
    assert "성분 코드를 찾지 못한 제품(타이레놀8시간정)이 있어 성분 단위로는 확인하지 못했습니다" in text
    assert text.count("[확인 불가]") == 1  # 아세트아미노펜(성분) × 타이레놀8시간정 만. 제품 × 제품(와파린정 × 타이레놀8시간정)은 제품 쌍으로 조회한다
    assert sorted(e.section_type for e in result.evidence) == ["contraindication", "contraindication_none"]


async def test_ambiguous_product_name_that_is_not_an_ingredient_still_asks_which_product():
    tool, _ = _ingredient_tool([_crow("D000001", "D000147")])
    result = await tool.run({"products": ["와파린정", "타이레놀"]})  # 타이레놀은 성분 이름이 아니다 → 제품 되묻기
    assert result.text.startswith("[확인 필요]") and {c["product_key"] for c in result.candidates} == {"drug:300", "drug:310"}


async def test_name_that_equals_an_ingredient_is_used_as_ingredient_even_when_many_products_contain_it():
    INGREDIENT_NAMES.append({"item_seq": "999", "ingr_name": "타이레놀", "dur_ingr_code": "D000555"})
    try:
        tool, reader = _ingredient_tool([_crow("D000001", "D000555", names=("와파린", "타이레놀"))])
        result = await tool.run({"products": ["와파린정", "타이레놀"]})  # 제품은 타이레놀정500…/타이레놀8시간정 두 개(앞부분만 일치)
    finally:
        INGREDIENT_NAMES.pop()
    assert not result.is_error and "타이레놀(성분)" in result.text
    assert "정확히 일치하는 제품명이 없고 성분 이름과 일치해" in result.text and "[성분 기준 조회]" in result.text
    assert result.candidates == []


async def test_exact_duplicate_product_names_are_never_turned_into_an_ingredient():
    INGREDIENT_NAMES.append({"item_seq": "999", "ingr_name": "중복정", "dur_ingr_code": "D000556"})

    def duplicated(sql, params):
        if "SELECT DISTINCT product_key" in sql and "= :value" in sql and params.get("value") == "중복정":
            return [
                {"product_key": "drug:1", "product_name": "중복정", "manufacturer": "A사", "product_type": "drug"},
                {"product_key": "drug:2", "product_name": "중복정", "manufacturer": "B사", "product_type": "drug"},
            ]
        return _db(sql, params)

    reader = FakeReader(_ingredient_handler([], base=duplicated))
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(reader), RdsContraStore())
    try:
        result = await tool.run({"products": ["와파린정", "중복정"]})
    finally:
        INGREDIENT_NAMES.pop()
    assert result.text.startswith("[확인 필요]") and {c["product_key"] for c in result.candidates} == {"drug:1", "drug:2"}


async def test_ingredient_and_health_food_combination_keeps_the_food_policy():
    tool, _ = _ingredient_tool([_crow("D000001", "D000147")])
    result = await tool.run({"products": ["아세트아미노펜", "홍삼정"]})
    assert "병용금기 판정 불가" in result.text and "혈압강하제" in result.text


async def test_sqlite_store_has_no_ingredient_fallback():
    import tempfile
    from pathlib import Path

    from app.llm.v2.contra_index import build_index
    from app.llm.v2.contra_store import ContraStore

    path = Path(tempfile.mkdtemp()) / "c.sqlite"
    build_index([], path)
    reader = FakeReader(_db)
    tool = ContraindicationTool(make_settings(), FakeReaderFactory(reader), ContraStore(path))
    result = await tool.run({"products": ["와파린정", "아세트아미노펜"]})
    assert result.text.startswith("[검색 결과 없음]")


async def test_find_ingredient_collects_every_code_for_the_same_name():
    rows = [
        {"ingr_name": "가나성분", "dur_ingr_code": "D000010"}, {"ingr_name": "가나성분", "dur_ingr_code": "D000011"},
        {"ingr_name": "가나성분", "dur_ingr_code": None},
    ]
    reader = FakeReader(lambda sql, params: rows)
    match, without_code = await RdsContraStore().find_ingredient(reader, "가나성분")
    assert match.codes == ("D000010", "D000011") and without_code is False

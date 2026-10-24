"""병용금기 인덱스 변환(build_index)과 조회(ContraStore) 테스트. pyarrow 없이 합성 행으로 검증한다."""
import datetime
import sqlite3
import tempfile
from pathlib import Path

from app.llm.v3.contra_index import build_index
from app.llm.v3.contra_store import ContraStore, ContraStoreError
from app.llm.v3.tests.helpers import raises


def row(a, b, content="심실성빈맥", ingr=("약가",), mix=("약나",), remark=None, level="품목", **extra):
    base = {
        "level": level, "item_seq": a, "mixture_item_seq": b, "ingr_names": list(ingr), "mixture_ingr_names": list(mix),
        "prohbt_content": content, "remark": remark, "form_name": "정제", "dur_seq": "100",
        "notification_date": datetime.date(2012, 3, 2), "snapshot": datetime.date(2026, 10, 13),
    }
    base.update(extra)
    return base


def _build(rows):
    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "contra.sqlite"
    return build_index(rows, path), path


def test_build_keeps_only_valid_product_pairs_and_dedupes_both_directions():
    rows = [
        row("200", "100"),                       # 큰 코드가 앞 → (100, 200) 으로 저장되고 성분도 맞바뀐다
        row("100", "200", ingr=("약나",), mix=("약가",)),  # 같은 규칙의 반대 방향 → 합쳐진다
        row("100", "300", level="성분"),          # 성분 규칙 행은 제외
        row("100", None),                        # 짝이 없는 행 제외
        row("100", "100"),                       # 같은 제품끼리 제외
        row("100", "400", content=None),         # 금기 내용이 없는 행 제외
        row("100", "500", remark="48시간 이내 병용금기"),
    ]
    stats, path = _build(rows)
    assert stats["rows_read"] == 7 and stats["pair_rows"] == 3 and stats["pairs"] == 2
    assert stats["snapshot"] == "2026-10-13"
    store = ContraStore(path)
    assert store.meta("snapshot") == "2026-10-13" and store.meta("pairs") == "2"


def test_lookup_orients_ingredients_to_the_asked_order_and_both_directions_match():
    stats, path = _build([row("200", "100", ingr=("나성분",), mix=("가성분",))])  # 저장: 100 쪽 가성분, 200 쪽 나성분
    store = ContraStore(path)
    forward = store.lookup(["100", "200"]).pairs[0]
    backward = store.lookup(["200", "100"]).pairs[0]
    assert (forward.first, forward.second) == ("100", "200")
    assert forward.rules[0].first_names == "가성분" and forward.rules[0].second_names == "나성분"
    assert backward.rules[0].first_names == "나성분" and backward.rules[0].second_names == "가성분"  # 질문 순서를 따른다
    rule = forward.rules[0]
    assert rule.content == "심실성빈맥" and rule.notified == "2012-03-02" and rule.form_name == "정제"


def test_lookup_reports_missing_pair_and_which_products_have_rules():
    _, path = _build([row("100", "200")])
    result = ContraStore(path).lookup(["100", "200", "999"])
    pairs = {(p.first, p.second): p.rules for p in result.pairs}
    assert len(pairs) == 3 and pairs[("100", "200")] and pairs[("100", "999")] == [] and pairs[("200", "999")] == []
    assert result.has_rules == {"100": True, "200": True, "999": False}


def test_lookup_returns_distinct_rules_with_remark_conditions():
    _, path = _build([row("100", "200"), row("100", "200", content="다른 사유", remark="소생 등의 응급상황 제외")])
    rules = ContraStore(path).lookup(["100", "200"]).pairs[0].rules
    assert [r.content for r in rules] == ["심실성빈맥", "다른 사유"] and rules[1].remark == "소생 등의 응급상황 제외"
    assert len(ContraStore(path).lookup(["100", "200"], max_rules_per_pair=1).pairs[0].rules) == 1


def test_values_are_bound_not_interpolated():
    _, path = _build([row("100", "200")])
    result = ContraStore(path).lookup(["100' OR '1'='1", "200"])
    assert result.pairs[0].rules == [] and result.has_rules["100' OR '1'='1"] is False


def test_store_is_read_only_and_missing_file_is_an_error():
    _, path = _build([row("100", "200")])
    connection = ContraStore(path)._connect()
    try:
        with raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM pairs")
    finally:
        connection.close()
    with raises(ContraStoreError):
        ContraStore(Path(path).with_name("없음.sqlite"))


def test_pairs_among_lists_pairs_inside_the_given_set():
    _, path = _build([row("100", "200"), row("100", "300"), row("200", "900")])
    assert ContraStore(path).pairs_among(["100", "200", "300"]) == [("100", "200"), ("100", "300")]
    assert ContraStore(path).pairs_among(["100"]) == []


def test_failed_build_leaves_no_output_file():
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "contra.sqlite"

    def broken():
        yield row("100", "200")
        raise RuntimeError("boom")

    with raises(RuntimeError):
        build_index(broken(), out)
    assert not out.exists()

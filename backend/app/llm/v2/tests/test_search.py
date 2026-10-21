"""검색 모듈 테스트: 가짜 Reader 로 SQL 모양, 바인딩, 분기 동작을 검증한다 (DB 없이)."""
import json

from app.llm.v2.embedder import to_vector_text
from app.llm.v2.search import (
    SearchConfigError,
    check_config,
    filter_clause,
    find_by_key,
    find_products,
    like_literal,
    rank_exact,
    retrieve,
)
from app.llm.v2.tests.helpers import FakeReader, make_settings, raises

CONFIG_ROW = {"schema_version": 2, "embedding_version": "amazon.titan-embed-text-v2:0:dim=1024:normalize=true", "dimensions": 1024}
PRODUCT = {"product_key": "drug:1", "product_name": "타이레놀정500밀리그램", "manufacturer": "한국얀센", "product_type": "drug"}


def test_like_literal_escapes_wildcards():
    assert like_literal("a%b_c\\d") == "a\\%b\\_c\\\\d"


def test_vector_text_is_pgvector_literal():
    assert to_vector_text([0.5, -1, 2.25]) == "[0.5,-1.0,2.25]"


async def test_find_products_stops_at_first_matching_stage():
    def handler(sql, params):
        return [PRODUCT] if params["value"] == "타이레놀%" else []

    reader = FakeReader(handler)
    found = await find_products(reader, "run1", " 타이레놀 ")
    assert found["mode"] == "prefix" and not found["truncated"]
    assert [c[1]["value"] for c in reader.calls] == ["타이레놀", "타이레놀%"]  # contains 단계는 실행하지 않음


async def test_find_products_skips_contains_for_short_names():
    reader = FakeReader(lambda sql, params: [])
    found = await find_products(reader, "run1", "타이")
    assert found["mode"] == "not_found"
    assert [c[1]["value"] for c in reader.calls] == ["타이", "타이%"]


async def test_find_products_marks_truncated_at_limit_plus_one():
    rows = [{**PRODUCT, "product_key": f"drug:{i}"} for i in range(21)]
    found = await find_products(FakeReader(lambda s, p: rows), "run1", "타이레놀")
    assert found["truncated"] and len(found["products"]) == 20


async def test_find_products_user_text_only_in_params():
    reader = FakeReader(lambda s, p: [])
    hostile = "x'; DROP TABLE product_search.product_links; --"
    await find_products(reader, "run1", hostile, product_type="drug")
    for sql, params in reader.calls:
        assert "DROP" not in sql and "x'" not in sql
        assert ":value" in sql and params["product_type"] == "drug"


async def test_find_products_validates_input():
    with raises(ValueError):
        await find_products(FakeReader(lambda s, p: []), "run1", "   ")
    with raises(ValueError):
        await find_products(FakeReader(lambda s, p: []), "run1", "a", product_type="x")


def test_filter_clause_binds_everything():
    where, params = filter_clause("run1", ["drug:1'; --"], "drug", "usage")
    assert "drug:1" not in where and "'" not in where
    assert params == {"run_id": "run1", "product_keys": ["drug:1'; --"], "product_type": "drug", "section_type": "usage"}
    assert "CAST(:product_keys AS text[])" in where


async def test_rank_exact_binds_vector_as_cast_text_and_parses_rows():
    def handler(sql, params):
        if "AS distance" in sql:
            return [{"content_hash": "h1", "content": "복용법", "product_type": "drug", "section_type": "usage", "distance": 0.25}]
        return [
            {
                "product_key": "drug:1", "product_name": "A", "manufacturer": "M", "source_refs": json.dumps(["usage"]),
                "metadata": "{}", "source_s3_key": "s3://b/k", "snapshot": "2026-10-13", "sale_status": None, "total": 3,
            }
        ]

    reader = FakeReader(handler)
    hits = await rank_exact(reader, "run1", "[0.1,0.2]", 5, ["drug:1"], None, "usage")
    ranking_sql, ranking_params = reader.calls[0]
    assert "CAST(:q AS vector)" in ranking_sql and "MATERIALIZED" in ranking_sql
    assert ranking_params["q"] == "[0.1,0.2]" and ranking_params["top_k"] == 5
    assert "[0.1" not in ranking_sql
    assert hits[0].distance == 0.25 and hits[0].source_count == 3 and hits[0].sources[0]["source_refs"] == ["usage"]
    sources_sql, sources_params = reader.calls[1]
    assert sources_params["content_hash"] == "h1" and ":content_hash" in sources_sql and "LIMIT 50" in sources_sql


async def test_rank_exact_rejects_bad_top_k():
    with raises(ValueError):
        await rank_exact(FakeReader(lambda s, p: []), "run1", "[1]", 0)


async def test_check_config_mismatch_stops_search():
    settings = make_settings()
    await check_config(FakeReader(lambda s, p: [CONFIG_ROW]), settings)
    for rows in ([], [{**CONFIG_ROW, "dimensions": 512}], [{**CONFIG_ROW, "embedding_version": "other"}], [{**CONFIG_ROW, "schema_version": 1}]):
        with raises(SearchConfigError):
            await check_config(FakeReader(lambda s, p, r=rows: r), settings)


def _handler(snapshot="run1", products=(PRODUCT,), hits=True):
    def handler(sql, params):
        if "pipeline_config" in sql:
            return [CONFIG_ROW]
        if "active_snapshot" in sql:
            return [{"run_id": snapshot}] if snapshot else []
        if "SELECT DISTINCT product_key" in sql:
            return list(products)
        if "AS distance" in sql:
            return [{"content_hash": "h", "content": "c", "product_type": "drug", "section_type": "usage", "distance": 0.1}] if hits else []
        return [{"product_key": "drug:1", "product_name": "A", "manufacturer": "M", "source_refs": [], "metadata": {},
                 "source_s3_key": "k", "snapshot": "2026-10-13", "sale_status": None, "total": 1}]
    return handler


async def test_retrieve_no_snapshot():
    outcome = await retrieve(FakeReader(_handler(snapshot=None)), make_settings(), "[1]", "타이레놀")
    assert outcome.status == "no_snapshot"


async def test_retrieve_product_not_found_and_ambiguous():
    outcome = await retrieve(FakeReader(_handler(products=())), make_settings(), "[1]", "없는약")
    assert outcome.status == "product_not_found"
    many = [{**PRODUCT, "product_key": f"drug:{i}"} for i in range(21)]
    outcome = await retrieve(FakeReader(_handler(products=many)), make_settings(), "[1]", "약")
    assert outcome.status == "ambiguous_product"


async def test_retrieve_requires_product_name_unless_global_enabled():
    reader = FakeReader(_handler())
    outcome = await retrieve(reader, make_settings(), "[1]", None)
    assert outcome.status == "needs_product_name"
    assert not any("AS distance" in sql for sql, _ in reader.calls)  # 전체 스캔 쿼리를 실행하지 않음
    outcome = await retrieve(FakeReader(_handler()), make_settings(allow_global_search=True), "[1]", None)
    assert outcome.status == "ok" and outcome.match_mode == "global"


async def test_retrieve_scopes_ranking_to_resolved_products():
    reader = FakeReader(_handler())
    outcome = await retrieve(reader, make_settings(), "[1]", "타이레놀", section_type="usage", top_k=3)
    assert outcome.status == "ok" and len(outcome.hits) == 1
    ranking_params = next(p for sql, p in reader.calls if "AS distance" in sql)
    assert ranking_params["product_keys"] == ["drug:1"] and ranking_params["section_type"] == "usage"


async def test_retrieve_drops_hits_beyond_max_distance():
    def handler(sql, params):
        if "AS distance" in sql:
            return [
                {"content_hash": "near", "content": "c", "product_type": "drug", "section_type": "usage", "distance": 0.30},
                {"content_hash": "edge", "content": "c", "product_type": "drug", "section_type": "usage", "distance": 0.65},
                {"content_hash": "far", "content": "c", "product_type": "drug", "section_type": "storage", "distance": 0.90},
            ]
        return _handler()(sql, params)

    outcome = await retrieve(FakeReader(handler), make_settings(), "[1]", "타이레놀", max_distance=0.65)
    assert [h.content_hash for h in outcome.hits] == ["near", "edge"] and outcome.filtered == 1
    unfiltered = await retrieve(FakeReader(handler), make_settings(), "[1]", "타이레놀")
    assert len(unfiltered.hits) == 3 and unfiltered.filtered == 0
    with raises(ValueError):
        await retrieve(FakeReader(handler), make_settings(), "[1]", "타이레놀", max_distance=3)


async def test_retrieve_rejects_unknown_section():
    with raises(ValueError):
        await retrieve(FakeReader(_handler()), make_settings(), "[1]", "타이레놀", section_type="drop table")


async def test_find_products_prefers_original_over_stripped_variant():
    reader = FakeReader(lambda sql, params: [PRODUCT] if params["value"] == "대한포도당주사액(5%)" else [])
    found = await find_products(reader, "run1", "대한포도당주사액(5%)")
    assert found["mode"] == "exact" and found["approximate"] is False and len(reader.calls) == 1


async def test_find_products_falls_back_to_stripped_variant_and_flags_it():
    reader = FakeReader(lambda sql, params: [PRODUCT] if params["value"] == "대한포도당주사액%" else [])
    found = await find_products(reader, "run1", "대한포도당주사액(7%)")
    assert found["mode"] == "prefix" and found["approximate"] is True and found["matched_as"] == "대한포도당주사액"
    values = [c[1]["value"] for c in reader.calls]
    # 단계가 바깥 루프: exact(원본, 괄호 제거) → prefix(원본, 괄호 제거)
    assert values == ["대한포도당주사액(7%)", "대한포도당주사액", like_literal("대한포도당주사액(7%)") + "%", "대한포도당주사액%"]


async def test_find_products_fullwidth_input_matches_without_being_approximate():
    reader = FakeReader(lambda sql, params: [PRODUCT] if params["value"] == "대한포도당주사액(5%)" else [])
    found = await find_products(reader, "run1", "대한포도당주사액（5%）")
    assert found["mode"] == "exact" and found["approximate"] is False


async def test_retrieve_asks_for_clarification_when_several_products_match():
    two = [PRODUCT, {**PRODUCT, "product_key": "drug:2", "product_name": "타이레놀8시간"}]
    reader = FakeReader(_handler(products=two))
    outcome = await retrieve(reader, make_settings(), "[1]", "타이레놀")
    assert outcome.status == "needs_clarification" and [p["product_key"] for p in outcome.products] == ["drug:1", "drug:2"]
    assert not any("AS distance" in sql for sql, _ in reader.calls)  # 순위 검색을 하지 않는다


async def test_retrieve_with_product_key_skips_name_matching():
    def handler(sql, params):
        if "product_key = :product_key" in sql:
            return [PRODUCT]
        return _handler()(sql, params)

    reader = FakeReader(handler)
    outcome = await retrieve(reader, make_settings(), "[1]", "타이레놀", product_key="drug:1")
    assert outcome.status == "ok" and outcome.match_mode == "key"
    assert not any("lower(product_name)" in sql for sql, _ in reader.calls)
    ranking = next(p for sql, p in reader.calls if "AS distance" in sql)
    assert ranking["product_keys"] == ["drug:1"]


async def test_retrieve_unknown_or_malformed_product_key():
    outcome = await retrieve(FakeReader(_handler(products=())), make_settings(), "[1]", None, product_key="drug:999")
    assert outcome.status == "product_not_found"
    for bad in ("drug:1'; DROP TABLE x; --", "other:1", "drug:", "drug:1 2"):
        with raises(ValueError):
            await find_by_key(FakeReader(lambda s, p: []), "run1", bad)


async def test_retrieve_marks_approximate_single_match():
    reader = FakeReader(lambda sql, params: ([PRODUCT] if params.get("value") == "타이레놀%" else []) if "SELECT DISTINCT" in sql else _handler()(sql, params))
    outcome = await retrieve(reader, make_settings(), "[1]", "타이레놀(아세트아미노펜)")
    assert outcome.status == "ok" and outcome.approximate is True and outcome.matched_as == "타이레놀"


async def test_fetch_section_texts_binds_parameters_orders_and_dedupes():
    from app.llm.v2.search import fetch_section_texts

    rows = [
        {"chunk_index": 0, "content_hash": "a", "content": " 첫 문단 "},
        {"chunk_index": 1, "content_hash": "b", "content": "둘째 문단"},
        {"chunk_index": 2, "content_hash": "a", "content": " 첫 문단 "},  # 같은 본문은 한 번만
        {"chunk_index": 3, "content_hash": "c", "content": "   "},  # 빈 문단은 버린다
    ]
    reader = FakeReader(lambda sql, params: rows)
    result = await fetch_section_texts(reader, "run1", "health_food:9", "precautions")
    assert result == {"chunks": ["첫 문단", "둘째 문단"], "truncated": False}
    sql, params = reader.calls[0]
    assert params == {"run_id": "run1", "product_key": "health_food:9", "section_type": "precautions", "limit": 101}
    assert "health_food:9" not in sql and "precautions" not in sql  # 값은 SQL 문자열에 이어 붙이지 않는다
    assert "ORDER BY l.chunk_index" in sql and sql.count(":") == sql.count(":run_id") + sql.count(":product_key") + sql.count(":section_type") + sql.count(":limit")


async def test_fetch_section_texts_reports_truncation_and_validates_inputs():
    from app.llm.v2.search import fetch_section_texts

    rows = [{"chunk_index": i, "content_hash": f"h{i}", "content": f"문단{i}"} for i in range(4)]
    reader = FakeReader(lambda sql, params: rows)
    result = await fetch_section_texts(reader, "run1", "drug:1", "usage", limit=3)
    assert result["chunks"] == ["문단0", "문단1", "문단2"] and result["truncated"] is True
    reader = FakeReader(lambda sql, params: [])
    for bad in (("health_food:9; DROP", "precautions", 100), ("health_food:9", "nonsense", 100), ("health_food:9", "precautions", 0), ("health_food:9", "precautions", 201)):
        with raises(ValueError):
            await fetch_section_texts(reader, "run1", bad[0], bad[1], bad[2])
    assert reader.calls == []  # 검증 실패는 DB 에 도달하지 않는다

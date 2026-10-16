"""질문 임베딩 + 검색 도구 테스트."""
import io
import json

from app.llm.v2.embedder import EmbeddingError, QueryEmbedder, validate_vector
from app.llm.v2.search import SearchHit, SearchOutcome
from app.llm.v2.tests.helpers import FakeReader, FakeReaderFactory, make_settings, raises
from app.llm.v2.tools import TOOL_NAME, DrugSearchTool, build_tool_spec, format_outcome


class FakeBedrock:
    def __init__(self, vector=None, error=None):
        self.requests = []
        self._vector = vector if vector is not None else [0.1] * 1024
        self._error = error

    def invoke_model(self, **kwargs):
        self.requests.append(kwargs)
        if self._error:
            raise self._error
        return {"body": io.BytesIO(json.dumps({"embedding": self._vector}).encode())}


async def test_embedder_uses_pipeline_conditions():
    client = FakeBedrock()
    vector = await QueryEmbedder(make_settings(), client).embed("  임산부 복용  ")
    request = client.requests[0]
    assert request["modelId"] == "amazon.titan-embed-text-v2:0"
    assert json.loads(request["body"]) == {"inputText": "임산부 복용", "dimensions": 1024, "normalize": True}
    assert len(vector) == 1024


async def test_embedder_rejects_bad_vectors_and_empty_text():
    with raises(EmbeddingError):
        await QueryEmbedder(make_settings(), FakeBedrock(vector=[0.1] * 10)).embed("x")
    with raises(EmbeddingError):
        await QueryEmbedder(make_settings(), FakeBedrock(vector=[0.0] * 1024)).embed("x")
    with raises(EmbeddingError):
        await QueryEmbedder(make_settings(), FakeBedrock()).embed("   ")


async def test_embedder_error_does_not_echo_question():
    client = FakeBedrock(error=RuntimeError("input was 내 당뇨 약 질문"))
    with raises(EmbeddingError) as caught:
        await QueryEmbedder(make_settings(), client).embed("내 당뇨 약 질문")
    assert "당뇨" not in str(caught.value)


def test_validate_vector_nan():
    with raises(ValueError):
        validate_vector([float("nan")] * 1024, 1024)


def test_tool_spec_requires_product_name_unless_global():
    spec = build_tool_spec(False)
    assert spec["name"] == TOOL_NAME and spec["input_schema"]["required"] == ["product_name", "question"]
    assert build_tool_spec(True)["input_schema"]["required"] == ["question"]
    assert "usage" in spec["input_schema"]["properties"]["section"]["enum"]


def _hit(section="usage", distance=0.2, count=1, name="타이레놀정500밀리그램"):
    return SearchHit("h", "성인은 1회 1~2정", "drug", section, distance, count,
                     [{"product_key": "drug:1", "product_name": name, "manufacturer": "한국얀센"}])


def test_format_outcome_uses_source_header_and_evidence():
    outcome = SearchOutcome("ok", "run1", "prefix", [{"product_name": "타이레놀정500밀리그램"}], [_hit(), _hit("precautions", 0.4, 12)])
    result = format_outcome(outcome, "타이레놀")
    assert "[출처 | 타이레놀정500밀리그램 | 용법·용량 | 유사도 0.800]" in result.text
    assert "[출처 | 타이레놀정500밀리그램 외 11개 제품 | 주의사항 | 유사도 0.600]" in result.text
    assert [e.label for e in result.evidence] == ["타이레놀정500밀리그램 · 용법·용량", "타이레놀정500밀리그램 · 주의사항"]
    assert not result.is_error


def test_format_outcome_no_evidence_cases():
    for status in ("product_not_found", "ambiguous_product"):
        result = format_outcome(SearchOutcome(status, "run1"), "타이레놀")
        assert result.text.startswith("[검색 결과 없음]") and result.evidence == []
    assert format_outcome(SearchOutcome("ok", "run1", hits=[]), "타이레놀").evidence == []
    assert format_outcome(SearchOutcome("no_snapshot"), None).is_error
    assert format_outcome(SearchOutcome("needs_product_name", "run1"), None).is_error


def test_format_outcome_truncates_long_content():
    long_hit = SearchHit("h", "가" * 5000, "drug", "usage", 0.1, 1, [{"product_key": "k", "product_name": "A", "manufacturer": "M"}])
    text = format_outcome(SearchOutcome("ok", "r", hits=[long_hit]), "A").text
    assert len(text) < 2200 and text.endswith("(이하 생략)")


class FakeEmbedder:
    def __init__(self, error=None):
        self.texts = []
        self._error = error

    async def embed(self, text):
        self.texts.append(text)
        if self._error:
            raise self._error
        return [0.5, 0.5]


def _tool(handler, embedder=None, **settings):
    reader = FakeReader(handler)
    factory = FakeReaderFactory(reader)
    return DrugSearchTool(make_settings(**settings), factory, embedder or FakeEmbedder()), reader, factory


def _db(sql, params):
    config = {"schema_version": 2, "embedding_version": "amazon.titan-embed-text-v2:0:dim=1024:normalize=true", "dimensions": 1024}
    if "pipeline_config" in sql:
        return [config]
    if "active_snapshot" in sql:
        return [{"run_id": "run1"}]
    if "SELECT DISTINCT product_key" in sql:
        return [{"product_key": "drug:1", "product_name": "타이레놀", "manufacturer": "M", "product_type": "drug"}]
    if "AS distance" in sql:
        return [{"content_hash": "h", "content": "본문", "product_type": "drug", "section_type": "usage", "distance": 0.1}]
    return [{"product_key": "drug:1", "product_name": "타이레놀", "manufacturer": "M", "source_refs": [], "metadata": {},
             "source_s3_key": "k", "snapshot": "2026-10-13", "sale_status": None, "total": 1}]


async def test_tool_run_happy_path_embeds_outside_transaction_and_binds_vector():
    embedder = FakeEmbedder()
    tool, reader, factory = _tool(_db, embedder)
    result = await tool.run({"product_name": " 타이레놀 ", "question": "하루   몇 번 먹나요", "section": "usage"})
    assert embedder.texts == ["하루 몇 번 먹나요"] and factory.opened == 1
    assert "[출처 | 타이레놀 | 용법·용량" in result.text and len(result.evidence) == 1
    ranking = next(p for sql, p in reader.calls if "AS distance" in sql)
    assert ranking["q"] == "[0.5,0.5]" and ranking["section_type"] == "usage" and ranking["top_k"] == 5


async def test_tool_run_applies_max_distance_from_settings():
    def db(sql, params):
        if "AS distance" in sql:
            return [{"content_hash": "h", "content": "무관한 본문", "product_type": "drug", "section_type": "usage", "distance": 0.9}]
        return _db(sql, params)

    tool, _, _ = _tool(db)
    result = await tool.run({"product_name": "타이레놀", "question": "복용법"})
    assert result.evidence == [] and result.text.startswith("[검색 결과 없음]") and "무관한" not in result.text
    tool, _, _ = _tool(db, max_distance=1.0)
    assert len((await tool.run({"product_name": "타이레놀", "question": "복용법"})).evidence) == 1


async def test_tool_run_validates_arguments_without_touching_db():
    tool, reader, factory = _tool(_db)
    for bad in (None, "문자열", {"product_name": "A"}, {"product_name": "A", "question": "q", "section": "x; drop"},
                {"product_name": "A", "question": "q" * 400}, {"product_name": 5, "question": "q"}):
        result = await tool.run(bad)
        assert result.is_error and result.text.startswith("[인자 오류]"), bad
    assert reader.calls == [] and factory.opened == 0


async def test_tool_run_hides_internal_errors():
    def boom(sql, params):
        raise RuntimeError("password authentication failed for user master host db.internal")

    tool, _, _ = _tool(boom)
    result = await tool.run({"product_name": "A", "question": "q"})
    assert result.is_error and "master" not in result.text and "db.internal" not in result.text

    tool, _, _ = _tool(_db, FakeEmbedder(error=EmbeddingError("x")))
    assert (await tool.run({"product_name": "A", "question": "q"})).text == "[검색 오류] 지금은 정보를 조회할 수 없습니다."


async def test_tool_run_without_product_name_when_global_disabled():
    tool, _, _ = _tool(_db)
    result = await tool.run({"question": "두통에 먹는 약"})
    assert result.is_error and "제품명" in result.text


def test_format_outcome_lists_candidates_for_clarification():
    products = [
        {"product_key": "drug:1", "product_name": "대한포도당주사액(5%)", "manufacturer": "대한약품", "product_type": "drug"},
        {"product_key": "drug:2", "product_name": "대한포도당주사액(10%)", "manufacturer": "대한약품", "product_type": "drug"},
    ]
    result = format_outcome(SearchOutcome("needs_clarification", "run1", "prefix", products), "대한포도당주사액")
    assert result.text.startswith("[확인 필요]") and "product_key=drug:2" in result.text and "(10%)" in result.text
    assert result.evidence == [] and [c["product_key"] for c in result.candidates] == ["drug:1", "drug:2"]


def test_format_outcome_notes_approximate_match():
    outcome = SearchOutcome("ok", "run1", "prefix", [{"product_name": "대한포도당주사액(5%)"}], [_hit()], approximate=True)
    text = format_outcome(outcome, "대한포도당주사액(7%)").text
    assert text.startswith("[참고]") and "정확히 일치하는 제품이 없어" in text and "대한포도당주사액(5%)" in text


def test_display_name_shortens_export_tags_but_evidence_keeps_full_name():
    full = "신신티눈고(살리실산반창고)(수출명:SINSINCORNPLASTER)"
    outcome = SearchOutcome("ok", "run1", "exact", [{"product_name": full}], [_hit(name=full)])
    result = format_outcome(outcome, "신신티눈고")
    assert "[출처 | 신신티눈고(살리실산반창고) | 용법·용량" in result.text and "SINSINCORN" not in result.text
    assert result.evidence[0].product_name == full and "SINSINCORN" not in result.evidence[0].label


async def test_tool_run_normalizes_fullwidth_and_validates_product_key():
    tool, reader, _ = _tool(_db)
    await tool.run({"product_name": "타이레놀（500）", "question": "복용법"})
    assert any(p.get("value") == "타이레놀(500)" for _, p in reader.calls)
    result = await tool.run({"product_name": "A", "question": "q", "product_key": "drug:1'; --"})
    assert result.is_error and result.text.startswith("[인자 오류]")


async def test_tool_run_returns_candidates_for_agent():
    def db(sql, params):
        if "SELECT DISTINCT product_key" in sql:
            return [
                {"product_key": "drug:1", "product_name": "타이레놀정", "manufacturer": "M", "product_type": "drug"},
                {"product_key": "drug:2", "product_name": "타이레놀8시간", "manufacturer": "M", "product_type": "drug"},
            ]
        return _db(sql, params)

    tool, _, _ = _tool(db)
    result = await tool.run({"product_name": "타이레놀", "question": "복용법"})
    assert len(result.candidates) == 2 and result.evidence == [] and not result.is_error

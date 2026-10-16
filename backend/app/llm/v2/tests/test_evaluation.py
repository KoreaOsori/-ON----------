"""평가 코드 테스트: 순위/지표 계산, 케이스 생성, 케이스 로딩."""
import json
import tempfile
from pathlib import Path

from app.llm.v2.evaluation.build_cases import collect_products, make_cases
from app.llm.v2.evaluation.dataset import load_cases
from app.llm.v2.evaluation.retrieval_eval import evaluate, rank_of_expected, summarize
from app.llm.v2.search import SearchHit
from app.llm.v2.tests.helpers import raises


def hit(section, name="A", key="drug:1"):
    return SearchHit("h", "c", "drug", section, 0.1, 1, [{"product_key": key, "product_name": name}])


CASE = {"question": "A 복용법?", "query": "복용법", "product_name": "A", "expected_section": "usage"}


def test_rank_of_expected():
    hits = [hit("precautions"), hit("usage", name="B", key="drug:2"), hit("usage")]
    assert rank_of_expected(hits, CASE) == 3  # 같은 섹션이어도 다른 제품이면 정답이 아니다
    assert rank_of_expected(hits, CASE, require_section=False) == 1
    assert rank_of_expected([], CASE) is None
    assert rank_of_expected(hits, {**CASE, "product_key": "drug:2"}) == 2  # product_key 가 있으면 키로 판정


def test_summarize_hit_rate_and_mrr():
    ranks = [1, 2, None, 6]
    assert summarize(ranks, k=5) == {"cases": 4, "hit_rate": 0.5, "mrr": (1 + 0.5) / 4}
    assert summarize([], 5)["cases"] == 0


async def test_evaluate_runs_each_case():
    async def search(case, k):
        return [hit("precautions"), hit("usage")]

    result = await evaluate([CASE, CASE], search, k=5, verbose=False)
    assert result["section"] == {"cases": 2, "hit_rate": 1.0, "mrr": 0.5}
    assert result["product"]["mrr"] == 1.0


def _links(rows):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)


def test_build_cases_from_bundle_links():
    rows = []
    for i, name in enumerate(["가정", "나정", "다정", "다정"]):  # 다정은 이름이 겹쳐 제외
        for section in ("overview", "usage", "storage"):
            rows.append({"product_key": f"drug:{i}", "product_name": name, "product_type": "drug", "section_type": section})
    rows.append({"product_key": "hf:1", "product_name": "건기식", "product_type": "health_food", "section_type": "usage"})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "links.jsonl"
        path.write_text(_links(rows), encoding="utf-8")
        products = collect_products(path)
    cases = make_cases(products, max_cases=10, seed=1)
    assert {c["product_name"] for c in cases} == {"가정", "나정"}
    assert all(c["expected_section"] in ("usage", "storage") and c["product_name"] in c["question"] for c in cases)
    assert all(c["product_name"] not in c["query"] for c in cases)
    assert make_cases(products, 10, seed=1) == cases  # 같은 seed 면 같은 결과
    assert len(make_cases(products, 1, seed=1)) == 1


def test_load_cases():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cases.jsonl"
        assert load_cases(path) == []  # 파일이 없으면 빈 목록 (가짜 케이스를 만들지 않는다)
        path.write_text(json.dumps(CASE, ensure_ascii=False) + "\n", encoding="utf-8")
        assert load_cases(path) == [CASE]
        path.write_text(json.dumps({"question": "q"}) + "\n", encoding="utf-8")
        with raises(ValueError):
            load_cases(path)

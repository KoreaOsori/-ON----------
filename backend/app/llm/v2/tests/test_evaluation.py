"""평가 코드 테스트: 순위/지표 계산, 케이스 생성, 케이스 로딩."""
import json
import tempfile
from pathlib import Path

from app.llm.v2.evaluation.build_cases import collect_products, make_cases
from app.llm.v2.evaluation.dataset import OFFTOPIC_QUESTIONS, load_cases, load_offtopic
from app.llm.v2.evaluation.distance_stats import (
    default_grid, distance_stats, format_table, overlap_warning, percentile, suggest_threshold, threshold_table,
)
from app.llm.v2.evaluation.retrieval_eval import (
    evaluate, find_expected, offtopic_top_distances, rank_of_expected, summarize,
)
from app.llm.v2.search import SearchHit
from app.llm.v2.tests.helpers import raises


def hit(section, name="A", key="drug:1", distance=0.1):
    return SearchHit("h", "c", "drug", section, distance, 1, [{"product_key": key, "product_name": name}])


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


async def test_evaluate_returns_distance_of_expected_hit():
    async def search(case, k):
        return [hit("precautions", distance=0.30), hit("usage", distance=0.55)]

    async def nothing(case, k):
        return [hit("precautions", distance=0.30)]

    result = await evaluate([CASE], search, k=5, verbose=False)
    assert result["distances"] == [0.55]  # 정답 청크의 거리 (1등 청크의 거리가 아니다)
    assert (await evaluate([CASE], nothing, k=5, verbose=False))["distances"] == [None]  # 못 찾으면 None
    rank, found = find_expected([hit("usage", distance=0.4)], CASE)
    assert rank == 1 and found.distance == 0.4
    assert find_expected([], CASE) is None


def test_percentile_nearest_rank():
    values = [float(i) for i in range(1, 11)]  # 1..10
    assert percentile(values, 0.9) == 9.0
    assert percentile(values, 1.0) == 10.0
    assert percentile([5.0], 0.9) == 5.0
    with raises(ValueError):
        percentile([], 0.5)


def test_distance_stats_counts_missing_and_summarizes():
    stats = distance_stats([0.2, None, 0.4, 0.6, 0.8])
    assert stats == {"count": 4, "missing": 1, "min": 0.2, "median": 0.5, "p90": 0.8, "max": 0.8}
    empty = distance_stats([None, None])
    assert empty["count"] == 0 and empty["missing"] == 2 and empty["median"] is None
    assert distance_stats([])["count"] == 0


def test_threshold_table_and_suggestion():
    correct = [0.3, 0.5, 0.7, None]       # 4건 중 못 찾음 1건
    unrelated = [0.9, 1.0, 0.8, 0.6]
    rows = {row.threshold: row for row in threshold_table(correct, unrelated, [0.5, 0.7, 0.85, 1.0])}
    assert rows[0.5].kept == 0.5 and rows[0.5].blocked == 1.0      # 정답 2/4 통과, 무관 4/4 차단
    assert rows[0.7].kept == 0.75 and rows[0.7].blocked == 0.75    # 0.6 은 통과해 버린다
    assert rows[0.85].kept == 0.75 and rows[0.85].blocked == 0.5
    assert rows[1.0].blocked == 0.0
    suggested = suggest_threshold(list(rows.values()))
    assert suggested.threshold == 0.7 and suggested.score == 1.5   # 0.5 도 1.5 → 같으면 큰 임계값
    assert threshold_table([], unrelated) == [] and suggest_threshold([]) is None
    text = format_table(list(rows.values()), suggested)
    assert "추천 후보" in text and text.count("추천 후보") == 1


def test_default_grid_and_overlap_warning():
    grid = default_grid()
    assert grid[0] == 0.40 and grid[-1] == 1.20 and len(grid) == 17
    assert overlap_warning([0.3, 0.7], [0.9, 1.0]) is None
    assert "나눌 수 없" in overlap_warning([0.3, 0.9], [0.8, 1.0])
    assert overlap_warning([None], [0.8]) is None


async def test_offtopic_top_distances_skips_empty():
    seen = []

    async def top1(case, question):
        seen.append((case["product_name"], question))
        return None if question == "빈" else 0.9

    distances = await offtopic_top_distances([{"product_name": "A"}, {"product_name": "B"}], ["x", "빈"], top1)
    assert distances == [0.9, 0.9] and len(seen) == 4


def test_load_offtopic_default_and_file():
    assert load_offtopic(None) == OFFTOPIC_QUESTIONS and len(OFFTOPIC_QUESTIONS) >= 8
    assert load_offtopic(None) is not OFFTOPIC_QUESTIONS  # 복사본
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "off.txt"
        path.write_text("# 주석\n질문1\n\n질문2\n", encoding="utf-8")
        assert load_offtopic(path) == ["질문1", "질문2"]
        path.write_text("# 없음\n", encoding="utf-8")
        with raises(ValueError):
            load_offtopic(path)

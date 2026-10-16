"""RAG 검색 성능 평가: HitRate@k, MRR (강의의 evaluation/retrieval_eval.py 에 해당).

    python -m app.llm.v2.evaluation.retrieval_eval --k 5                # 제품 범위 검색(도구가 실제로 하는 방식)
    python -m app.llm.v2.evaluation.retrieval_eval --k 5 --mode global  # 제품명 없이 전체 검색(느릴 수 있음)

- scoped : product_name 으로 범위를 좁힌 뒤 query(제품명 제외)로 순위를 매긴다. '올바른 섹션이 위에 오는가'를 본다.
- global : 제품명 없이 전체 문장(question)으로 검색한다. '제품과 섹션을 모두 찾는가'를 본다. 전체 exact 스캔이라 느리다.
평가는 거리 임계값(max_distance)을 적용하지 않는다. 출력되는 거리로 적합한 임계값을 고른다
(정답 근거의 거리 분포와 무관한 근거의 거리 분포 사이를 가르는 값).
정답 판정: 결과 청크의 출처에 정답 제품이 있고 section_type 이 정답 섹션이면 적중.
이 스크립트는 읽기 전용 DB 연결과 Bedrock 임베딩을 쓴다(= 환경변수 설정 필요).
"""
import argparse
import asyncio
import dataclasses
from typing import Awaitable, Callable

from app.llm.v2.config import V2Settings
from app.llm.v2.db import build_engine, reader_factory_for
from app.llm.v2.embedder import QueryEmbedder, to_vector_text
from app.llm.v2.evaluation.dataset import CASES
from app.llm.v2.search import SearchHit, retrieve

Search = Callable[[dict, int], Awaitable[list[SearchHit]]]


def _product_matches(hit: SearchHit, case: dict) -> bool:
    for source in hit.sources:
        if case.get("product_key"):
            if source["product_key"] == case["product_key"]:
                return True
        elif source["product_name"].strip().lower() == case["product_name"].strip().lower():
            return True
    return False


def rank_of_expected(hits: list[SearchHit], case: dict, require_section: bool = True) -> int | None:
    """정답이 처음 나타나는 순위(1부터). 없으면 None."""
    for index, hit in enumerate(hits, start=1):
        if _product_matches(hit, case) and (not require_section or hit.section_type == case["expected_section"]):
            return index
    return None


def summarize(ranks: list[int | None], k: int) -> dict[str, float]:
    """HitRate@k = Top-k 안에 정답이 있는 비율, MRR = 정답 순위의 역수 평균."""
    if not ranks:
        return {"cases": 0, "hit_rate": 0.0, "mrr": 0.0}
    hits = [1 if r is not None and r <= k else 0 for r in ranks]
    reciprocal = [1 / r if r is not None and r <= k else 0.0 for r in ranks]
    return {"cases": len(ranks), "hit_rate": sum(hits) / len(ranks), "mrr": sum(reciprocal) / len(ranks)}


async def evaluate(cases: list[dict], search: Search, k: int, verbose: bool = True) -> dict[str, dict[str, float]]:
    strict: list[int | None] = []
    product_only: list[int | None] = []
    for case in cases:
        hits = await search(case, k)
        rank = rank_of_expected(hits, case, require_section=True)
        strict.append(rank)
        product_only.append(rank_of_expected(hits, case, require_section=False))
        if verbose:
            got = [f"{h.section_type}({h.distance:.2f})" for h in hits]  # (코사인 거리) - max_distance 튜닝 참고
            print(f"{case['question']} -> {got} | expected={case['expected_section']} | rank={rank}")
    return {"section": summarize(strict, k), "product": summarize(product_only, k)}


def make_search(settings: V2Settings, mode: str):
    """(search 함수, 정리 함수). DB 엔진/임베더를 만든다."""
    if mode == "global":
        settings = dataclasses.replace(settings, allow_global_search=True)
    engine = build_engine(settings)
    open_reader = reader_factory_for(engine)
    embedder = QueryEmbedder(settings)

    async def search(case: dict, k: int) -> list[SearchHit]:
        text = case["question"] if mode == "global" else case["query"]
        vector = to_vector_text(await embedder.embed(text))
        async with open_reader() as reader:
            outcome = await retrieve(
                reader, settings, vector,
                product_name=None if mode == "global" else case["product_name"],
                top_k=k,
            )
        return outcome.hits

    return search, engine.dispose


async def main(k: int = 5, mode: str = "scoped") -> None:
    if not CASES:
        raise SystemExit("평가 케이스가 없습니다. 먼저 build_cases 로 생성하세요 (evaluation/dataset.py 설명 참고).")
    search, close = make_search(V2Settings.from_env(), mode)
    try:
        result = await evaluate(CASES, search, k)
    finally:
        await close()
    print(f"[{mode}] 케이스 {result['section']['cases']}개")
    print(f"HitRate@{k} (제품+섹션) = {result['section']['hit_rate']:.3f}")
    print(f"MRR        (제품+섹션) = {result['section']['mrr']:.3f}")
    if mode == "global":
        print(f"HitRate@{k} (제품만)   = {result['product']['hit_rate']:.3f}")
        print(f"MRR        (제품만)   = {result['product']['mrr']:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", choices=("scoped", "global"), default="scoped")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.k, arguments.mode))

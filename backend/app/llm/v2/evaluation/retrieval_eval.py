"""RAG 검색 성능 평가: HitRate@k, MRR (강의의 evaluation/retrieval_eval.py 에 해당).

    python -m app.llm.v2.evaluation.retrieval_eval --k 5                # 제품 범위 검색(도구가 실제로 하는 방식)
    python -m app.llm.v2.evaluation.retrieval_eval --k 5 --mode global  # 제품명 없이 전체 검색(느릴 수 있음)
    python -m app.llm.v2.evaluation.retrieval_eval --mode offtopic      # 약과 무관한 질문의 1등 거리 분포
    python -m app.llm.v2.evaluation.retrieval_eval --mode calibrate     # 정답 거리 + 무관 거리 → 임계값 후보 표

- scoped : product_name 으로 범위를 좁힌 뒤 query(제품명 제외)로 순위를 매긴다. '올바른 섹션이 위에 오는가'를 본다.
- global : 제품명 없이 전체 문장(question)으로 검색한다. '제품과 섹션을 모두 찾는가'를 본다. 전체 exact 스캔이라 느리다.
- offtopic : 약과 무관한 질문을 각 케이스의 제품 범위에서 검색해 1등 거리의 분포를 본다(무관한 문단이 얼마나 가까워 보이는가).
- calibrate: scoped 의 정답 거리 분포 + offtopic 분포를 합쳐 LLM_V2_MAX_DISTANCE 후보 표를 만든다.
  scoped/calibrate 는 정답 근거의 거리 요약(최소·중앙값·90%·최대)을 함께 출력한다.
평가는 거리 임계값(max_distance)을 적용하지 않는다. 출력되는 거리로 적합한 임계값을 고른다
(정답 근거의 거리 분포와 무관한 근거의 거리 분포 사이를 가르는 값).
정답 판정: 결과 청크의 출처에 정답 제품이 있고 section_type 이 정답 섹션이면 적중.
이 스크립트는 읽기 전용 DB 연결과 Bedrock 임베딩을 쓴다(= 환경변수 설정 필요).
"""
import argparse
import asyncio
import dataclasses
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.llm.v2.config import V2Settings
from app.llm.v2.db import build_engine, reader_factory_for
from app.llm.v2.embedder import QueryEmbedder, to_vector_text
from app.llm.v2.evaluation.dataset import CASES, load_offtopic
from app.llm.v2.evaluation.distance_stats import (
    distance_stats, format_stats, format_table, overlap_warning, suggest_threshold, threshold_table,
)
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


def find_expected(hits: list[SearchHit], case: dict, require_section: bool = True) -> tuple[int, SearchHit] | None:
    """정답이 처음 나타나는 (순위(1부터), 청크). 없으면 None."""
    for index, hit in enumerate(hits, start=1):
        if _product_matches(hit, case) and (not require_section or hit.section_type == case["expected_section"]):
            return index, hit
    return None


def rank_of_expected(hits: list[SearchHit], case: dict, require_section: bool = True) -> int | None:
    """정답이 처음 나타나는 순위(1부터). 없으면 None."""
    found = find_expected(hits, case, require_section)
    return found[0] if found else None


def summarize(ranks: list[int | None], k: int) -> dict[str, float]:
    """HitRate@k = Top-k 안에 정답이 있는 비율, MRR = 정답 순위의 역수 평균."""
    if not ranks:
        return {"cases": 0, "hit_rate": 0.0, "mrr": 0.0}
    hits = [1 if r is not None and r <= k else 0 for r in ranks]
    reciprocal = [1 / r if r is not None and r <= k else 0.0 for r in ranks]
    return {"cases": len(ranks), "hit_rate": sum(hits) / len(ranks), "mrr": sum(reciprocal) / len(ranks)}


async def evaluate(cases: list[dict], search: Search, k: int, verbose: bool = True) -> dict[str, Any]:
    """반환: section/product 지표, distances(케이스별 정답 근거의 코사인 거리, 못 찾으면 None)."""
    strict: list[int | None] = []
    product_only: list[int | None] = []
    distances: list[float | None] = []
    for case in cases:
        hits = await search(case, k)
        found = find_expected(hits, case, require_section=True)
        rank = found[0] if found else None
        strict.append(rank)
        distances.append(found[1].distance if found else None)
        product_only.append(rank_of_expected(hits, case, require_section=False))
        if verbose:
            got = [f"{h.section_type}({h.distance:.2f})" for h in hits]  # (코사인 거리) - max_distance 튜닝 참고
            print(f"{case['question']} -> {got} | expected={case['expected_section']} | rank={rank}")
    return {"section": summarize(strict, k), "product": summarize(product_only, k), "distances": distances}


Top1 = Callable[[dict, str], Awaitable[float | None]]


async def offtopic_top_distances(cases: list[dict], questions: list[str], top1: Top1) -> list[float]:
    """각 (케이스 제품, 무관 질문) 쌍의 1등 거리. 문단이 하나도 없는 쌍은 건너뛴다."""
    distances: list[float] = []
    for case in cases:
        for question in questions:
            distance = await top1(case, question)
            if distance is not None:
                distances.append(distance)
    return distances


class Runtime:
    """DB 엔진 + 임베더. 평가 모드들이 공유한다."""

    def __init__(self, settings: V2Settings) -> None:
        self.settings = settings
        self.engine = build_engine(settings)
        self.open_reader = reader_factory_for(self.engine)
        self.embedder = QueryEmbedder(settings)
        self._vectors: dict[str, str] = {}

    async def vector(self, text: str) -> str:
        if text not in self._vectors:  # 같은 문장은 한 번만 임베딩한다
            self._vectors[text] = to_vector_text(await self.embedder.embed(text))
        return self._vectors[text]

    def search(self, mode: str) -> Search:
        async def search(case: dict, k: int) -> list[SearchHit]:
            text = case["question"] if mode == "global" else case["query"]
            vector = await self.vector(text)
            async with self.open_reader() as reader:
                outcome = await retrieve(
                    reader, self.settings, vector,
                    product_name=None if mode == "global" else case["product_name"],
                    top_k=k,
                )
            return outcome.hits

        return search

    def offtopic_top1(self) -> Top1:
        async def top1(case: dict, question: str) -> float | None:
            vector = await self.vector(question)
            async with self.open_reader() as reader:
                outcome = await retrieve(
                    reader, self.settings, vector,
                    product_name=case["product_name"], product_key=case.get("product_key"), top_k=1,
                )
            return outcome.hits[0].distance if outcome.hits else None

        return top1

    async def close(self) -> None:
        await self.engine.dispose()


def make_search(settings: V2Settings, mode: str):
    """(search 함수, 정리 함수). 기존 호출부 호환용."""
    if mode == "global":
        settings = dataclasses.replace(settings, allow_global_search=True)
    runtime = Runtime(settings)
    return runtime.search(mode), runtime.close


def print_scoped(result: dict[str, Any], k: int, mode: str) -> None:
    print(f"[{mode}] 케이스 {result['section']['cases']}개")
    print(f"HitRate@{k} (제품+섹션) = {result['section']['hit_rate']:.3f}")
    print(f"MRR        (제품+섹션) = {result['section']['mrr']:.3f}")
    if mode == "global":
        print(f"HitRate@{k} (제품만)   = {result['product']['hit_rate']:.3f}")
        print(f"MRR        (제품만)   = {result['product']['mrr']:.3f}")
    print(format_stats("정답 근거 거리", distance_stats(result["distances"])))


async def main(
    k: int = 5,
    mode: str = "scoped",
    offtopic_limit: int = 20,
    offtopic_file: Path | None = None,
    verbose: bool = True,
) -> None:
    if not CASES:
        raise SystemExit("평가 케이스가 없습니다. 먼저 build_cases 로 생성하세요 (evaluation/dataset.py 설명 참고).")
    settings = V2Settings.from_env()
    if mode == "global":
        settings = dataclasses.replace(settings, allow_global_search=True)
    runtime = Runtime(settings)
    try:
        if mode in ("scoped", "global"):
            print_scoped(await evaluate(CASES, runtime.search(mode), k, verbose), k, mode)
            return

        questions = load_offtopic(offtopic_file)
        sample = CASES[: max(1, offtopic_limit)]
        unrelated = await offtopic_top_distances(sample, questions, runtime.offtopic_top1())
        print(f"[무관 질문] 제품 {len(sample)}개 × 질문 {len(questions)}개 = {len(unrelated)}건")
        print(format_stats("무관 질문 1등 거리", distance_stats(unrelated)))
        if mode == "offtopic":
            print("정답 근거의 거리와 비교하려면 --mode calibrate 를 사용하세요.")
            return

        result = await evaluate(CASES, runtime.search("scoped"), k, verbose)
        print_scoped(result, k, "scoped")
        rows = threshold_table(result["distances"], unrelated)
        suggested = suggest_threshold(rows)
        print()
        print(format_table(rows, suggested))
        warning = overlap_warning(result["distances"], unrelated)
        if warning:
            print(warning)
        if suggested:
            print(
                f"\n통과율+차단율이 가장 큰 후보: {suggested.threshold:.2f} "
                f"(정답 통과 {suggested.kept:.1%}, 무관 차단 {suggested.blocked:.1%}). "
                "후보일 뿐이니 표를 보고 정하고, PowerShell에서는 $env:LLM_V2_MAX_DISTANCE = \"값\" 으로 시험하세요."
            )
    finally:
        await runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", choices=("scoped", "global", "offtopic", "calibrate"), default="scoped")
    parser.add_argument("--offtopic-limit", type=int, default=20, help="무관 질문과 짝지을 제품 수(앞에서부터)")
    parser.add_argument("--offtopic-file", type=Path, default=None, help="무관 질문 파일(한 줄에 하나). 기본은 내장 목록")
    parser.add_argument("--quiet", action="store_true", help="케이스별 출력 생략")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.k, arguments.mode, arguments.offtopic_limit, arguments.offtopic_file, not arguments.quiet))

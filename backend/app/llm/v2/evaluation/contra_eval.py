"""병용금기 도구 평가: 실제 병용금기 쌍을 찾아내는가, 규칙 없는 쌍에 규칙을 만들어 내지 않는가. Bedrock/Claude 호출 없음.

    python -m app.llm.v2.evaluation.contra_eval --limit 100
    python -m app.llm.v2.evaluation.contra_eval --contra-db app/llm/v2/dev_data/contraindication.sqlite

- 검색 DB 에 적재된 의약품 중 병용금기 인덱스에 규칙이 있는 쌍(양성)과, 규칙이 없는 쌍(대조군, seed 고정 무작위)을 만든다.
- 각 쌍을 도구로 두 번 확인한다: product_key 로(식별 문제를 제외한 조회 자체), DB 제품명 그대로(사용자가 이름을 말하는 경우).
- 기대: 양성은 key 로 100% '규칙 있음', 대조군은 100% '규칙 없음'(규칙을 만들어 내면 안 된다).
  이름으로는 같은 이름·접두어를 가진 제품이 있으면 되묻기(clarify)로 갈 수 있다 — 오류가 아니라 되묻기 비율로 본다.
읽기 전용 DB 연결만 필요하다(환경변수 설정 필요).
"""
import argparse
import asyncio
import random
from collections import Counter
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.llm.v2.agent import DEFAULT_CONTRA_DB
from app.llm.v2.config import V2Settings
from app.llm.v2.contra_store import ContraStore
from app.llm.v2.contra_tool import ContraindicationTool
from app.llm.v2.db import build_engine, reader_factory_for
from app.llm.v2.search import SCHEMA, active_run_id
from app.llm.v2.tools import ToolResult

RunTool = Callable[[list[str]], Awaitable[ToolResult]]


def outcome_of(result: ToolResult) -> str:
    """도구 결과 → found | none | clarify | not_found | other."""
    if result.text.startswith("[확인 필요]"):
        return "clarify"
    if result.text.startswith("[검색 결과 없음]") or result.text.startswith("[확인 불가]"):
        return "not_found"
    kinds = {e.section_type for e in result.evidence}
    if kinds & {"contraindication", "contraindication_ingredient"}:
        return "found"
    if kinds == {"contraindication_none"}:
        return "none"
    return "other"


def make_negatives(keys: list[str], positives: set[tuple[str, str]], count: int, seed: int = 7) -> list[tuple[str, str]]:
    """규칙이 없는 쌍(seed 고정). positives 는 (작은 seq, 큰 seq)."""
    rng = random.Random(seed)
    seqs = sorted({k for k in keys})
    negatives: list[tuple[str, str]] = []
    tries = 0
    while len(negatives) < count and tries < count * 50 and len(seqs) >= 2:
        tries += 1
        a, b = sorted(rng.sample(seqs, 2))
        if (a, b) not in positives and (a, b) not in negatives:
            negatives.append((a, b))
    return negatives


async def evaluate_pairs(
    positives: list[tuple[str, str]], negatives: list[tuple[str, str]], names: dict[str, str], run_tool: RunTool
) -> dict[str, Any]:
    """각 쌍을 key 와 이름으로 확인해 결과 분포를 센다. names: seq → 제품명."""
    report: dict[str, Counter] = {
        "positive/key": Counter(), "positive/name": Counter(), "negative/key": Counter(), "negative/name": Counter(),
    }
    problems: list[str] = []
    for label, pairs in (("positive", positives), ("negative", negatives)):
        for a, b in pairs:
            by_key = outcome_of(await run_tool([f"drug:{a}", f"drug:{b}"]))
            by_name = outcome_of(await run_tool([names[a], names[b]]))
            report[f"{label}/key"][by_key] += 1
            report[f"{label}/name"][by_name] += 1
            expected = "found" if label == "positive" else "none"
            if by_key != expected and len(problems) < 10:
                problems.append(f"[{label}/key→{by_key}] {names[a]} × {names[b]}")
    return {"counts": report, "problems": problems, "positives": len(positives), "negatives": len(negatives)}


def format_report(report: dict[str, Any]) -> str:
    lines = [f"양성 쌍 {report['positives']}개 · 대조군 {report['negatives']}개"]
    for group, expected in (("positive", "found"), ("negative", "none")):
        for how in ("key", "name"):
            counts: Counter = report["counts"][f"{group}/{how}"]
            total = sum(counts.values())
            if not total:
                continue
            detail = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
            lines.append(f"{group:<8}/{how:<4} 기대({expected}) {counts[expected] / total:>6.1%} | {detail}")
    lines += [f"  {p}" for p in report["problems"]]
    lines.append("found=규칙 있음, none=규칙 없음, clarify=제품 되묻기, not_found=제품 못 찾음. negative 에서 found 가 나오면 심각한 오류입니다.")
    return "\n".join(lines)


async def main(contra_db: Path | None, limit: int) -> None:
    settings = V2Settings.from_env()
    store = ContraStore(contra_db or settings.contra_db_path or DEFAULT_CONTRA_DB)
    engine = build_engine(settings)
    open_reader = reader_factory_for(engine)
    tool = ContraindicationTool(settings, open_reader, store)
    try:
        async with open_reader() as reader:
            run_id = await active_run_id(reader)
            if run_id is None:
                raise SystemExit("활성 스냅샷이 없습니다.")
            rows = await reader.fetch(
                f"SELECT DISTINCT product_key, product_name FROM {SCHEMA}.product_links "
                "WHERE run_id = :run_id AND section_type = 'overview' AND product_type = 'drug' ORDER BY product_key",
                {"run_id": run_id},
            )
        names = {row["product_key"].split(":", 1)[1]: row["product_name"] for row in rows}
        found_pairs = await asyncio.to_thread(store.pairs_among, list(names), limit)
        positives = found_pairs[:limit]
        negatives = make_negatives(list(names), set(found_pairs), len(positives) or limit)

        async def run_tool(products: list[str]) -> ToolResult:
            return await tool.run({"products": products})

        print(f"DB 의약품 {len(names)}개 중 병용금기 쌍 {len(found_pairs)}개")
        print(format_report(await evaluate_pairs(positives, negatives, names, run_tool)))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contra-db", type=Path, default=None, help="병용금기 인덱스(기본: 설정 또는 dev_data/contraindication.sqlite)")
    parser.add_argument("--limit", type=int, default=100, help="양성 쌍 수 상한")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.contra_db, arguments.limit))

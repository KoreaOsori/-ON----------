"""Claude 모델 비교 (예: Haiku vs Sonnet). 같은 질문, 같은 DB·도구·프롬프트·한도에서 모델만 바꿔 돌린다.

    python -m app.llm.v2.evaluation.model_compare \
        --model haiku=<Bedrock 모델 ID> --model sonnet=<Bedrock 모델 ID> --limit 30

- --model 을 생략하면 config 의 haiku/sonnet 기본 ID(v1 설정과 동일, 미검증)로 비교한다. 다른 모델은 라벨=ID 로 지정.
  리전은 us-east-1 고정. provider 는 LLM_V2_PROVIDER 를 따른다.
- 질문은 evaluation/generated/cases.jsonl(기본) 또는 --questions 로 지정한 JSONL 의 question 필드.
  expected_section/product_name 이 있는 케이스는 '올바른 제품·섹션 근거를 찾아왔는가'도 자동 집계한다.
- 자동 지표는 비용/속도/안정성/검색 행동 비교용이다. 답변 문장의 품질은 저장된 JSONL 을 사람이 읽고 판단한다.
  (이 파일에는 답변 본문이 들어가므로 evaluation/generated/ 에만 저장되고 git 에서 제외된다.)
- 한 질문마다 모델들을 순서대로 실행한다(속도 제한을 피하고 같은 시점의 DB 를 보게 하려고).
"""
import argparse
import asyncio
import dataclasses
import json
import time
from pathlib import Path
from typing import Any

from app.llm.v2.agent import AgentAnswer, DrugInfoAgent
from app.llm.v2.config import ConfigError, V2Settings
from app.llm.v2.db import build_engine, reader_factory_for
from app.llm.v2.embedder import QueryEmbedder
from app.llm.v2.evaluation.dataset import DEFAULT_CASES_PATH, GENERATED_DIR, load_cases
from app.llm.v2.harness import Limits
from app.llm.v2.llm_client import build_create_message
from app.llm.v2.tools import DrugSearchTool

FAILURE_STOPS = ("error", "timeout", "budget", "refusal")


def judge(answer: AgentAnswer, case: dict) -> dict[str, bool | None]:
    """검색 행동 판정. 기대 섹션이 없는 질문은 None(집계 제외).

    section_hit : 기대 섹션의 근거를 하나라도 가져왔는가
    product_hit : 그 근거가 기대 제품의 것인가 (여러 제품이 공유하는 본문이면 제품 구분이 불가능해 인정)
    """
    expected = case.get("expected_section")
    if not expected:
        return {"section_hit": None, "product_hit": None}
    name = (case.get("product_name") or "").strip().lower()
    section_items = [e for e in answer.evidence if e.section_type == expected]
    product_items = [e for e in section_items if e.shared_count > 1 or e.product_name.strip().lower() == name]
    return {"section_hit": bool(section_items), "product_hit": bool(product_items)}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, float]:
    """runs: [{answer: AgentAnswer, judge: {...}}] → 한 모델의 요약."""
    n = len(runs)
    answers = [r["answer"] for r in runs]
    judged = [r["judge"] for r in runs if r["judge"]["section_hit"] is not None]
    seconds = sorted(a.elapsed_seconds for a in answers)
    return {
        "questions": n,
        "grounded_rate": _mean([1.0 if a.grounded else 0.0 for a in answers]),
        "no_evidence_rate": _mean([1.0 if a.stop_reason == "no_evidence" else 0.0 for a in answers]),
        "clarification_rate": _mean([1.0 if a.stop_reason == "needs_clarification" else 0.0 for a in answers]),
        "failure_rate": _mean([1.0 if a.stop_reason in FAILURE_STOPS else 0.0 for a in answers]),
        "avg_seconds": _mean(seconds),
        "p90_seconds": seconds[min(n - 1, int(n * 0.9))] if n else 0.0,
        "avg_tool_calls": _mean([float(len(a.tools_used)) for a in answers]),
        "avg_rounds": _mean([float(a.rounds) for a in answers]),
        "avg_input_tokens": _mean([float(a.input_tokens) for a in answers]),
        "avg_output_tokens": _mean([float(a.output_tokens) for a in answers]),
        "judged": len(judged),
        "section_hit_rate": _mean([1.0 if j["section_hit"] else 0.0 for j in judged]),
        "product_hit_rate": _mean([1.0 if j["product_hit"] else 0.0 for j in judged]),
    }


async def compare(
    cases: list[dict], agents: dict[str, DrugInfoAgent], verbose: bool = True
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """(모델별 실행 결과, 사람이 읽을 전체 기록) 을 돌려준다."""
    runs: dict[str, list[dict[str, Any]]] = {label: [] for label in agents}
    records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        record: dict[str, Any] = {"question": case["question"], "case": case, "models": {}}
        for label, agent in agents.items():
            answer = await agent.run(case["question"])
            verdict = judge(answer, case)
            runs[label].append({"answer": answer, "judge": verdict})
            record["models"][label] = {
                "answer": answer.answer,
                "stop_reason": answer.stop_reason,
                "grounded": answer.grounded,
                "sources": answer.sources,
                "tools_used": len(answer.tools_used),
                "rounds": answer.rounds,
                "seconds": round(answer.elapsed_seconds, 2),
                "input_tokens": answer.input_tokens,
                "output_tokens": answer.output_tokens,
                "tool_trace": answer.tool_trace,
                **verdict,
            }
            if verbose:
                print(
                    f"[{index}/{len(cases)}] {label:>8} stop={answer.stop_reason:<11} grounded={answer.grounded!s:<5} "
                    f"tools={len(answer.tools_used)} {answer.elapsed_seconds:5.1f}s "
                    f"tok={answer.input_tokens}/{answer.output_tokens} sec_hit={verdict['section_hit']}"
                )
        records.append(record)
    return runs, records


def format_summary(summaries: dict[str, dict[str, float]]) -> str:
    rows = [
        ("질문 수", "questions", "{:.0f}"),
        ("근거 기반 답변 비율", "grounded_rate", "{:.1%}"),
        ("근거 없음으로 끝난 비율", "no_evidence_rate", "{:.1%}"),
        ("제품 되묻기로 끝난 비율", "clarification_rate", "{:.1%}"),
        ("실패(오류/시간/한도/거절) 비율", "failure_rate", "{:.1%}"),
        ("평균 소요(초)", "avg_seconds", "{:.1f}"),
        ("p90 소요(초)", "p90_seconds", "{:.1f}"),
        ("평균 도구 호출 수", "avg_tool_calls", "{:.2f}"),
        ("평균 라운드 수", "avg_rounds", "{:.2f}"),
        ("평균 입력 토큰", "avg_input_tokens", "{:.0f}"),
        ("평균 출력 토큰", "avg_output_tokens", "{:.0f}"),
        ("기대 섹션 케이스 수", "judged", "{:.0f}"),
        ("기대 섹션 근거 확보율", "section_hit_rate", "{:.1%}"),
        ("기대 제품+섹션 근거 확보율", "product_hit_rate", "{:.1%}"),
    ]
    labels = list(summaries)
    lines = ["지표".ljust(30) + "".join(label.rjust(14) for label in labels)]
    for title, key, fmt in rows:
        lines.append(title.ljust(30) + "".join(fmt.format(summaries[l][key]).rjust(14) for l in labels))
    return "\n".join(lines)


def parse_models(items: list[str]) -> dict[str, str]:
    models: dict[str, str] = {}
    for item in items:
        label, sep, model_id = item.partition("=")
        if not sep or not label.strip() or not model_id.strip():
            raise ConfigError("--model 은 '라벨=모델ID' 형식이어야 합니다.")
        if label in models:
            raise ConfigError(f"라벨이 중복되었습니다: {label}")
        models[label.strip()] = model_id.strip()
    if len(models) < 2:
        raise ConfigError("비교하려면 --model 을 2개 이상 지정하세요.")
    return models


def build_agents(settings: V2Settings, models: dict[str, str]) -> tuple[dict[str, DrugInfoAgent], Any]:
    """모델마다 클라이언트만 다르게 하고 DB 엔진·도구·한도는 공유한다. (agents, 엔진)"""
    engine = build_engine(settings)
    tool = DrugSearchTool(settings, reader_factory_for(engine), QueryEmbedder(settings))
    limits = Limits.from_settings(settings)
    agents = {
        label: DrugInfoAgent(build_create_message(dataclasses.replace(settings, llm_model_id=model_id)), tool, limits)
        for label, model_id in models.items()
    }
    return agents, engine


async def main(args: argparse.Namespace) -> None:
    settings = V2Settings.from_env()
    models = parse_models(args.model) if args.model else {"haiku": settings.haiku_model_id, "sonnet": settings.sonnet_model_id}
    cases = load_cases(Path(args.questions))
    if not cases:
        raise SystemExit("질문이 없습니다. build_cases 로 생성하거나 --questions 로 JSONL 을 지정하세요.")
    cases = cases[: args.limit] if args.limit else cases

    agents, engine = build_agents(settings, models)
    try:
        runs, records = await compare(cases, agents)
    finally:
        await engine.dispose()

    print()
    print(format_summary({label: summarize_runs(items) for label, items in runs.items()}))

    out = Path(args.out) if args.out else GENERATED_DIR / f"model_compare-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\n답변 전문(사람이 읽고 비교) → {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude 모델 비교")
    parser.add_argument("--model", action="append", metavar="라벨=모델ID", help="2개 이상. 생략하면 haiku/sonnet 기본 ID")
    parser.add_argument("--questions", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개만 (0이면 전체)")
    parser.add_argument("--out")
    asyncio.run(main(parser.parse_args()))

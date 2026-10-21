"""제품명 입력 변형 평가: 사용자가 이름을 조금 다르게 말해도 올바른 제품에 닿는가.

    python -m app.llm.v2.evaluation.name_eval                       # 평가 케이스(cases.jsonl)의 제품으로
    python -m app.llm.v2.evaluation.name_eval --bundle app/llm/v2/dev_data/bundle --limit 300   # bundle 전체 제품으로

- DB 이름 → 사용자가 말할 법한 변형을 만들어 retrieve 에 넣고, 결과 상태를 분류한다.
- 임베딩(Bedrock)은 쓰지 않는다. 이름 식별만 보는 평가라 고정 벡터를 넣는다. 읽기 전용 DB 연결만 필요하다.
- 변형 종류
  original    DB 이름 그대로 (대조군: 정확 일치여야 한다)
  no_paren    괄호 부분을 뺀 이름 (괄호가 있는 제품만)
  fullwidth   괄호를 전각 （ ） 로 (괄호가 있는 제품만)
  spaced      이름 중간에 공백 하나 삽입
  half_prefix 이름 앞 절반만
  wrong_paren 괄호 안을 다른 내용으로 바꿈 (괄호가 있는 제품만)
- 결과 분류
  exact_hit      정확히 일치하는 제품 하나
  approx_hit     괄호 내용을 버려 찾은 제품 하나(= 정답, 답변에서 '근사' 표시가 붙음)
  clarify_incl   되묻기 후보에 정답이 있음
  clarify_excl   되묻기 후보에 정답이 없음
  sibling        입력이 '다른 실제 제품'의 이름과 같아 그 제품으로 확정됨 (예: 짧은 이름이 별개 제품) — 정상 동작
  wrong_product  그 밖에 다른 제품 하나로 확정됨  ← 가장 위험
  too_many       후보가 너무 많아 더 구체적인 이름을 요청
  not_found      못 찾음
"""
import argparse
import asyncio
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.llm.v2.config import V2Settings
from app.llm.v2.db import build_engine, reader_factory_for
from app.llm.v2.embedder import to_vector_text
from app.llm.v2.evaluation.build_cases import collect_products
from app.llm.v2.evaluation.dataset import CASES
from app.llm.v2.names import collapse_spaces, fold_brackets, strip_parentheticals
from app.llm.v2.search import SearchOutcome, retrieve

KINDS = ("original", "no_paren", "fullwidth", "spaced", "half_prefix", "wrong_paren")
CATEGORIES = (
    "exact_hit", "approx_hit", "clarify_incl", "clarify_excl", "sibling", "wrong_product", "too_many", "not_found", "other",
)
REACHED = ("exact_hit", "approx_hit", "clarify_incl")  # 정답에 닿았다(되묻기 후보 포함)
RESOLVED = ("exact_hit", "approx_hit")  # 되묻기 없이 정답으로 확정
BAD = ("wrong_product", "clarify_excl", "not_found")
_PAREN = re.compile(r"\([^()]*\)")

Lookup = Callable[[str], Awaitable[SearchOutcome]]


def make_variants(name: str) -> dict[str, str]:
    """DB 이름 → 종류별 변형. 해당 종류를 만들 수 없는 이름은 그 종류를 빼고 돌려준다."""
    variants = {"original": name}
    has_paren = bool(_PAREN.search(name))
    if has_paren:
        stripped = name
        while _PAREN.search(stripped):
            stripped = _PAREN.sub(" ", stripped)
        stripped = " ".join(stripped.split())
        if stripped and stripped != name:
            variants["no_paren"] = stripped
        variants["fullwidth"] = name.replace("(", "（").replace(")", "）")
        variants["wrong_paren"] = _PAREN.sub("(다른성분)", name, count=1)
    base = name.split("(")[0].rstrip()
    middle = len(base) // 2
    if len(base) >= 3 and middle >= 1:
        variants["spaced"] = name[:middle] + " " + name[middle:]
    half = max(3, len(name) // 2)
    if half < len(name):
        variants["half_prefix"] = name[:half]
    return variants


def _compact(text: str) -> str:
    return collapse_spaces(fold_brackets(text)).lower().replace(" ", "")


def classify(outcome: SearchOutcome, expected_key: str, typed: str | None = None) -> str:
    """typed 는 사용자가 입력했다고 가정한 문자열. 확정된 제품 이름이 입력(또는 입력에서 괄호를 뺀 것)과 같으면 sibling."""
    keys = [p["product_key"] for p in outcome.products]
    if outcome.status == "ok" and len(keys) == 1:
        if keys[0] != expected_key:
            if typed and _compact(outcome.products[0]["product_name"]) in (_compact(typed), _compact(strip_parentheticals(typed))):
                return "sibling"
            return "wrong_product"
        return "approx_hit" if outcome.approximate else "exact_hit"
    if outcome.status == "needs_clarification":
        return "clarify_incl" if expected_key in keys else "clarify_excl"
    if outcome.status == "ambiguous_product":
        return "too_many"
    if outcome.status == "product_not_found":
        return "not_found"
    return "other"


async def evaluate_names(products: list[dict[str, str]], lookup: Lookup, max_examples: int = 5) -> dict[str, Any]:
    """products: [{product_key, product_name}]. kind → {n, counts, examples(나쁜 결과)}."""
    report: dict[str, Any] = {kind: {"n": 0, "counts": {c: 0 for c in CATEGORIES}, "examples": []} for kind in KINDS}
    for product in products:
        for kind, text in make_variants(product["product_name"]).items():
            category = classify(await lookup(text), product["product_key"], text)
            entry = report[kind]
            entry["n"] += 1
            entry["counts"][category] += 1
            if category in BAD and len(entry["examples"]) < max_examples:
                entry["examples"].append((text, category))
    return report


def format_report(report: dict[str, Any]) -> str:
    header = f"{'변형':<12}{'n':>5} | " + " ".join(f"{c:>13}" for c in CATEGORIES[:-1]) + " | 정답 도달 | 한 번에 확정"
    lines = [header]
    for kind in KINDS:
        entry = report[kind]
        n = entry["n"]
        if not n:
            lines.append(f"{kind:<12}{0:>5} | (해당 제품 없음)")
            continue
        counts = entry["counts"]
        cells = " ".join(f"{counts[c]:>13}" for c in CATEGORIES[:-1])
        reached = sum(counts[c] for c in REACHED) / n
        resolved = sum(counts[c] for c in RESOLVED) / n
        lines.append(f"{kind:<12}{n:>5} | {cells} | {reached:>8.1%} | {resolved:>10.1%}")
    for kind in KINDS:
        for text, category in report[kind]["examples"]:
            lines.append(f"  [{kind}/{category}] {text!r}")  # repr: 줄바꿈 등 숨은 문자도 보이게
    return "\n".join(lines)


def load_products(bundle: Path | None, limit: int) -> list[dict[str, str]]:
    if bundle is not None:
        found = collect_products(bundle / "links.jsonl")
        items = sorted(found.items())
        products = [{"product_key": key, "product_name": p["product_name"]} for key, p in items]
    else:
        products = [{"product_key": c["product_key"], "product_name": c["product_name"]} for c in CASES if c.get("product_key")]
    if not products:
        raise SystemExit("평가할 제품이 없습니다. build_cases 로 케이스를 만들거나 --bundle 을 지정하세요.")
    return products[:limit]


async def main(bundle: Path | None, limit: int) -> None:
    products = load_products(bundle, limit)
    settings = V2Settings.from_env()
    engine = build_engine(settings)
    open_reader = reader_factory_for(engine)
    vector = to_vector_text([1.0] + [0.0] * 1023)  # 이름 식별만 보므로 고정 벡터(임베딩 호출 없음)

    async def lookup(name: str) -> SearchOutcome:
        async with open_reader() as reader:
            return await retrieve(reader, settings, vector, product_name=name, top_k=1)

    try:
        report = await evaluate_names(products, lookup)
    finally:
        await engine.dispose()
    print(f"제품 {len(products)}개")
    print(format_report(report))
    print(
        "\nwrong_product 가 0에 가까워야 안전합니다. clarify_* 는 사용자에게 되묻는 경우이고, "
        "sibling 은 입력이 다른 제품의 실제 이름과 같아 그 제품으로 간 정상 동작입니다(정답 도달에는 포함되지 않음)."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=None, help="vector_pipeline prepare 출력 폴더(links.jsonl 포함). 없으면 cases.jsonl")
    parser.add_argument("--limit", type=int, default=200, help="평가할 제품 수 상한")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.bundle, arguments.limit))

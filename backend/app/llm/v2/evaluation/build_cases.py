"""적재에 쓴 bundle(links.jsonl)에서 평가 케이스를 만든다. 표준 라이브러리만 사용, DB/AWS 호출 없음.

    python -m app.llm.v2.evaluation.build_cases --bundle /경로/sample-bundle --max-cases 60

정책
- 제품은 bundle 에 실제로 있는 것만 쓴다(그 제품에 해당 섹션 청크가 있을 때만 그 섹션 질문을 만든다).
- 질문 문장은 섹션별 고정 템플릿이다 → 사람이 읽고 보강해야 하는 '초안'이다. 실제 사용자 질문 로그가 생기면 교체한다.
- 같은 seed 면 같은 결과가 나온다.
"""
import argparse
import json
import random
from pathlib import Path

from app.llm.v2.evaluation.dataset import DEFAULT_CASES_PATH

# 섹션 → (전체 문장, 도구에 넘길 질문). {name} 은 제품명.
TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "benefits": [
        ("{name}은 어떤 증상에 쓰는 약이에요?", "어떤 증상에 쓰는 약인지 효능과 효과"),
        ("{name} 효능이 뭐예요?", "효능과 효과"),
    ],
    "usage": [
        ("{name} 복용 방법과 용량이 어떻게 되나요?", "복용 방법과 용량"),
        ("{name}은 하루에 몇 번 먹어요?", "하루 복용 횟수와 1회 용량"),
    ],
    "precautions": [
        ("{name} 먹을 때 주의할 점이 뭔가요?", "복용 시 주의사항"),
        ("{name} 임산부가 먹어도 되나요?", "임부 수유부 복용 시 주의사항"),
    ],
    "interactions": [
        ("{name}이랑 같이 먹으면 안 되는 약이 있나요?", "함께 복용하면 안 되는 약 상호작용"),
    ],
    "storage": [
        ("{name} 보관은 어떻게 하나요?", "보관 방법"),
    ],
    "ingredients": [
        ("{name}에는 어떤 성분이 들어 있나요?", "성분과 함량"),
    ],
}


def collect_products(links_path: Path) -> dict[str, dict]:
    """product_key → {name, type, sections}. links.jsonl 은 청크 단위 한 줄씩."""
    products: dict[str, dict] = {}
    with links_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            link = json.loads(line)
            entry = products.setdefault(
                link["product_key"],
                {"product_name": link["product_name"], "product_type": link["product_type"], "sections": set()},
            )
            entry["sections"].add(link["section_type"])
    return products


def make_cases(products: dict[str, dict], max_cases: int, seed: int = 7, product_type: str = "drug") -> list[dict]:
    rng = random.Random(seed)
    # 이름이 겹치는 제품은 정답을 하나로 정할 수 없어 제외한다.
    name_counts: dict[str, int] = {}
    for p in products.values():
        name_counts[p["product_name"]] = name_counts.get(p["product_name"], 0) + 1
    keys = sorted(k for k, p in products.items() if p["product_type"] == product_type and name_counts[p["product_name"]] == 1)
    rng.shuffle(keys)

    cases: list[dict] = []
    for key in keys:
        product = products[key]
        sections = [s for s in TEMPLATES if s in product["sections"]]
        if not sections:
            continue
        section = rng.choice(sections)
        full, query = rng.choice(TEMPLATES[section])
        cases.append(
            {
                "question": full.format(name=product["product_name"]),
                "query": query,
                "product_name": product["product_name"],
                "product_key": key,
                "expected_section": section,
            }
        )
        if len(cases) >= max_cases:
            break
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="bundle 에서 평가 케이스 초안 생성")
    parser.add_argument("--bundle", required=True, help="vector_pipeline prepare 출력 폴더 (links.jsonl 포함)")
    parser.add_argument("--out", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--max-cases", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--product-type", choices=("drug", "health_food"), default="drug")
    args = parser.parse_args()

    products = collect_products(Path(args.bundle) / "links.jsonl")
    cases = make_cases(products, args.max_cases, args.seed, args.product_type)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as stream:
        for case in cases:
            stream.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"{len(cases)}개 케이스 → {out}")


if __name__ == "__main__":
    main()

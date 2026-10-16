"""RAG 검색 정확도 평가용 테스트 케이스 (강의의 evaluation/dataset.py 에 해당).

각 케이스
- question         : 사용자가 실제로 물을 법한 전체 문장 (제품명 포함)
- query            : LLM 이 도구에 넘길 질문 (제품명 제외)  → 제품 범위 검색 평가에 사용
- product_name     : 도구의 product_name 인자
- expected_section : 정답 정보 유형 (benefits, usage, precautions ...)

실제 DB 에 적재된 제품으로 만들어야 의미가 있으므로, 케이스는 적재에 쓴 bundle 에서 생성한다.
    python -m app.llm.v2.evaluation.build_cases --bundle <bundle 폴더>
생성 파일이 없으면 CASES 는 빈 목록이다(존재하지 않는 제품명을 가짜로 넣지 않는다).
"""
import json
from pathlib import Path

GENERATED_DIR = Path(__file__).with_name("generated")
DEFAULT_CASES_PATH = GENERATED_DIR / "cases.jsonl"

REQUIRED_KEYS = ("question", "query", "product_name", "expected_section")


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict]:
    if not path.exists():
        return []
    cases = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            case = json.loads(line)
            missing = [k for k in REQUIRED_KEYS if not case.get(k)]
            if missing:
                raise ValueError(f"평가 케이스에 필수 키가 없습니다: {missing}")
            cases.append(case)
    return cases


CASES = load_cases()

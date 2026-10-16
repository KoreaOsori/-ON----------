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

# 약과 무관한 질문(임계값 보정용). 제품 범위 안에서도 가장 가까운 문단이 얼마나 먼지를 잰다.
# 사람이 보강할 수 있다: --offtopic-file (한 줄에 질문 하나).
OFFTOPIC_QUESTIONS = [
    "오늘 서울 날씨가 어때요?",
    "파이썬으로 리스트를 정렬하는 방법 알려줘",
    "자동차 보험 갱신은 어떻게 하나요?",
    "김치찌개 맛있게 끓이는 법",
    "주식 투자는 어떻게 시작하나요?",
    "아이폰 배터리를 오래 쓰는 방법",
    "제주도 2박 3일 여행 코스 추천해 주세요",
    "영어 단어를 빨리 외우는 방법",
    "월드컵에서 가장 많이 우승한 나라는?",
    "종합소득세 신고 기간이 언제예요?",
]


def load_offtopic(path: Path | None) -> list[str]:
    """path 가 없으면 기본 목록. 있으면 한 줄에 질문 하나(빈 줄·# 주석 제외)."""
    if path is None:
        return list(OFFTOPIC_QUESTIONS)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    questions = [line for line in lines if line and not line.startswith("#")]
    if not questions:
        raise ValueError("무관 질문 파일에 질문이 없습니다.")
    return questions

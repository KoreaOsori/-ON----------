"""제품명 다루기: 검색용 입력 변형, 표시용 줄임.

제품명에는 괄호가 많다 (예: '다이크로짇정(히드로클로로티아지드)', '대한포도당주사액(5%)', '...(수출명:ABC)').
- 검색: 사용자/모델이 넣은 이름을 몇 가지 변형으로 바꿔 차례로 시도한다. 변형은 **입력 쪽만** 가공한다.
  DB 컬럼 쪽을 가공(regexp_replace 등)하면 lower(product_name) 인덱스를 못 쓰기 때문이다.
- 표시: 모델에게 주는 출처 헤더/sources 에서만 '(수출명:...)', '(수출용)'을 줄인다. 검색·식별에는 원래 이름을 쓴다.
"""
import re
import unicodedata

_GROUP = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_EXPORT_TAG = re.compile(r"\s*\((?:수출명|수출용)[^()]*\)")
MAX_DISPLAY_CHARS = 60


def collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def strip_parentheticals(text: str) -> str:
    """() 와 [] 로 묶인 부분을 모두 제거 (중첩 포함)."""
    previous = None
    while previous != text:
        previous = text
        text = _GROUP.sub(" ", text)
    return collapse_spaces(text)


def name_variants(raw: str) -> list[tuple[str, bool]]:
    """검색 시도 순서대로 (이름, approximate) 목록.

    approximate=True 는 사용자가 말한 괄호 내용을 버린 변형이다. 의미가 달라질 수 있어서(예: (5%) → 전체 농도)
    이 변형으로 찾은 결과는 호출 쪽이 '정확히 일치하지 않음'으로 다뤄야 한다.
    공백·전각문자 정리는 approximate 가 아니다.
    """
    raw_lower = collapse_spaces(raw).lower()
    nfkc = collapse_spaces(unicodedata.normalize("NFKC", raw)).lower()  # 전각 괄호 등을 반각으로
    stripped = strip_parentheticals(nfkc)
    candidates = [
        (raw_lower, False),
        (nfkc, False),
        (raw_lower.replace(" ", ""), False),
        (nfkc.replace(" ", ""), False),
        (stripped, True),
        (stripped.replace(" ", ""), True),
    ]
    seen: set[str] = set()
    variants: list[tuple[str, bool]] = []
    for text, approximate in candidates:
        if text and text not in seen:
            seen.add(text)
            variants.append((text, approximate))
    return variants


def short_name(name: str) -> str:
    """표시용 이름: 수출 표기 괄호를 줄이고 길면 말줄임. 성분명 괄호는 식별에 도움이 되어 남긴다."""
    shortened = _EXPORT_TAG.sub("", name).strip() or name
    if len(shortened) > MAX_DISPLAY_CHARS:
        shortened = shortened[: MAX_DISPLAY_CHARS - 1] + "…"
    return shortened

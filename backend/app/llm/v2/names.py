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
# 전각 괄호만 반각으로. NFKC 전체 변환은 'Ⅱ'→'II', '㎎'→'mg' 처럼 제품명의 글자까지 바꿔서 따로 둔다.
_BRACKET_FOLD = str.maketrans({"（": "(", "）": ")", "［": "[", "］": "]"})


def collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def fold_brackets(text: str) -> str:
    return text.translate(_BRACKET_FOLD)


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
    folded = fold_brackets(raw_lower)  # 괄호만 정리: 'Ⅱ', '㎎' 같은 글자가 이름에 있어도 그대로 둔다
    nfkc = collapse_spaces(unicodedata.normalize("NFKC", raw)).lower()  # 그 밖의 전각/호환 문자까지 정리
    stripped_folded = strip_parentheticals(folded)
    stripped_nfkc = strip_parentheticals(nfkc)
    candidates = [
        (raw_lower, False),
        (folded, False),
        (nfkc, False),
        (raw_lower.replace(" ", ""), False),
        (folded.replace(" ", ""), False),
        (nfkc.replace(" ", ""), False),
        (stripped_folded, True),
        (stripped_nfkc, True),
        (stripped_folded.replace(" ", ""), True),
        (stripped_nfkc.replace(" ", ""), True),
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


MAX_GIVEN_PRODUCTS = 8
MAX_GIVEN_NAME_CHARS = 120


def clean_product_names(names: list[str] | None) -> list[str]:
    """호출자가 넘긴 제품명 목록(OCR 등) 정리: 공백 정리, 빈 값·중복(공백·대소문자 무시) 제거, 최대 개수 제한. 원문 표기는 유지한다."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = collapse_spaces(str(raw))[:MAX_GIVEN_NAME_CHARS]
        key = name.replace(" ", "").casefold()
        if name and key not in seen:
            seen.add(key)
            cleaned.append(name)
    return cleaned[:MAX_GIVEN_PRODUCTS]

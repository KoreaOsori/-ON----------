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


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def expand_with_given(name: str, given: list[str]) -> str:
    """도구에 넣을 이름이 호출자가 넘긴 제품명(OCR 등) 중 하나의 앞부분이면 그 전체 표기로 바꾼다.

    예: 모델이 '고려인삼분말캡슐'을 넣었고 givens 에 '고려인삼분말캡슐 (고려인삼과학주식회사)'가 있으면 제조사까지 적힌 표기를 쓴다
    (사용자가 되묻기 목록의 한 줄을 다시 입력하는 것과 같은 효과). 앞부분이 맞는 항목이 정확히 하나일 때만 바꾸고, 정확히 같거나
    여럿이면 그대로 둔다. 질문이 가리킨 이름을 임의로 다른 제품으로 바꾸지 않도록 '앞부분이 같은 더 긴 표기'만 대상으로 한다."""
    key = _compact(name)
    if len(key) < 2:
        return name
    keys = [(_compact(item), item) for item in given]
    if any(k == key for k, _ in keys):
        return name
    longer = [item for k, item in keys if k.startswith(key)]
    return longer[0] if len(longer) == 1 else name


_COMPANY_WORDS = re.compile(r"\(주\)|㈜|주식회사|\(유\)|㈲|유한회사|\(합\)")


def _company_key(text: str) -> str:
    """제조사 비교용 정규화: 회사 형태 표기·공백·괄호·대소문자를 무시한다."""
    folded = unicodedata.normalize("NFKC", text).lower()
    folded = _COMPANY_WORDS.sub("", folded)
    return re.sub(r"[\s()\[\]·.,-]", "", folded)


def narrow_by_manufacturer(raw_name: str, products: list[dict]) -> list[dict]:
    """이름이 같은 제품이 여럿일 때, 사용자가 입력에 제조사까지 적었으면 그 제조사 제품만 남긴다.

    되묻기 목록의 한 줄('제품명 (제조사)')을 그대로 다시 입력하는 흐름을 위한 것이다. 제조사가 입력에 없거나,
    모든 후보가 맞거나, 하나도 안 맞으면 그대로 돌려준다(임의로 고르지 않는다)."""
    if len(products) < 2:
        return products
    text = _company_key(raw_name)
    matched = [
        p for p in products
        if len(key := _company_key(str(p.get("manufacturer") or ""))) >= 2 and key in text
    ]
    return matched if 0 < len(matched) < len(products) else products

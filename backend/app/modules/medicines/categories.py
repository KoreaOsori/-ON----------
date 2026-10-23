"""약 검색의 하위 분류. 식약처 약효분류 코드(gold.drug.class_code)를 사용자용 이름으로 묶는다.

일반·전문의약품마다 판매 제품이 많은 대표 분류 10개 (2026-10 gold 기준 제품 수 순서).
같은 약효분류라도 일반·전문에서 이름이 다를 수 있다 (예: 02190 기타의 순환계용약 = 일반은 대부분 혈액순환 개선제).
어느 분류에도 들지 않는 약은 "기타". 코드는 앞자리가 같은 것을 모두 포함한다 (예: "026" = 0260~0269).
"""

OTHER = "기타"

_CODES = {
    "해열·진통·소염": ("01140",),
    "기침·가래": ("02220", "02230", "02290"),
    "소화·위장": ("0232", "0233", "0234", "0235", "0236", "0237", "0238", "0239"),
    "알레르기": ("01410", "01490"),
    "피부": ("026",),
    "눈": ("01310",),
    "코·귀·입": ("01320", "02310"),
    "비타민·영양": ("031", "032"),
    "간": ("03910",),
    "당뇨": ("03960",),
    "항생·감염": ("061", "062"),
    "정신·신경": ("0111", "0112", "0113", "0115", "0116", "0117", "0118", "0119"),
    "비뇨·생식": ("025",),
    "혈액": ("033",),
    "항암": ("042",),
}
_CIRCULATION = ("021",)

CATEGORIES: dict[str, dict[str, tuple[str, ...]]] = {
    "일반": {
        "비타민·영양": _CODES["비타민·영양"],
        "해열·진통·소염": _CODES["해열·진통·소염"],
        "피부": _CODES["피부"],
        "소화·위장": _CODES["소화·위장"],
        "혈액순환": _CIRCULATION,
        "기침·가래": _CODES["기침·가래"],
        "코·귀·입": _CODES["코·귀·입"],
        "눈": _CODES["눈"],
        "알레르기": _CODES["알레르기"],
        "간": _CODES["간"],
    },
    "전문": {
        "혈압·심장·혈관": _CIRCULATION,
        "항생·감염": _CODES["항생·감염"],
        "정신·신경": _CODES["정신·신경"],
        "당뇨": _CODES["당뇨"],
        "소화·위장": _CODES["소화·위장"],
        "해열·진통·소염": _CODES["해열·진통·소염"],
        "비뇨·생식": _CODES["비뇨·생식"],
        "혈액": _CODES["혈액"],
        "항암": _CODES["항암"],
        "알레르기": _CODES["알레르기"],
    },
}


def category_names() -> dict[str, list[str]]:
    return {medicine_type: [*groups, OTHER] for medicine_type, groups in CATEGORIES.items()}


def class_code_patterns(medicine_type: str, category: str) -> tuple[list[str], bool] | None:
    """SQL LIKE 패턴 목록과 "기타" 여부. 기타면 이 목록에 들지 않는(또는 분류가 없는) 약. 없는 분류면 None"""
    groups = CATEGORIES.get(medicine_type)
    if groups is None:
        return None
    if category == OTHER:
        return [f"{code}%" for codes in groups.values() for code in codes], True
    if category not in groups:
        return None
    return [f"{code}%" for code in groups[category]], False

"""제품명 변형/표시 줄임 테스트."""
from app.llm.v2.names import name_variants, short_name, strip_parentheticals


def test_variants_start_with_original_and_mark_stripped_as_approximate():
    variants = name_variants("다이크로짇정(히드로클로로티아지드)")
    assert variants[0] == ("다이크로짇정(히드로클로로티아지드)", False)
    assert ("다이크로짇정", True) in variants
    assert all(approximate for text, approximate in variants if "(" not in text)


def test_fullwidth_parentheses_and_spaces_are_not_approximate():
    variants = dict(name_variants("대한 포도당주사액 （5%）"))
    assert variants["대한포도당주사액(5%)"] is False  # 전각→반각 + 공백 제거
    assert variants["대한포도당주사액"] is True


def test_only_parenthetical_has_no_stripped_variant():
    assert name_variants("(5%)") == [("(5%)", False)]
    assert name_variants("   ") == []


def test_strip_parentheticals_handles_nested_and_brackets():
    assert strip_parentheticals("가나(다(라)마)바[사]") == "가나 바"  # 제거한 자리는 공백으로 둔다
    assert strip_parentheticals("안나카주사액20%(제일벤조산나트륨카페인주)(수출용)") == "안나카주사액20%"


def test_variants_are_unique_and_ordered():
    variants = name_variants("타이레놀")
    assert variants == [("타이레놀", False)]


def test_short_name_drops_export_tags_only():
    assert short_name("신신티눈고(살리실산반창고)(수출명:SINSINCORNPLASTER)") == "신신티눈고(살리실산반창고)"
    assert short_name("안나카주사액10%(제일벤조산나트륨카페인주)(수출용)") == "안나카주사액10%(제일벤조산나트륨카페인주)"
    assert short_name("다이크로짇정(히드로클로로티아지드)") == "다이크로짇정(히드로클로로티아지드)"
    assert short_name("(수출용)") == "(수출용)"  # 비면 원래 이름
    assert len(short_name("가" * 100)) == 60 and short_name("가" * 100).endswith("…")

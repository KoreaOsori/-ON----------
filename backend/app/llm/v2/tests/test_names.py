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


def test_bracket_fold_comes_before_nfkc_so_special_characters_survive():
    variants = [text for text, _ in name_variants("제이스고려로얄샷Ⅱ（전량수출용）")]
    assert variants[0] == "제이스고려로얄샷ⅱ（전량수출용）"
    assert variants[1] == "제이스고려로얄샷ⅱ(전량수출용)"       # 괄호만 반각 (Ⅱ 유지)
    assert "제이스고려로얄샷ii(전량수출용)" in variants[2:]     # NFKC 변형은 그 뒤
    assert variants.index("제이스고려로얄샷ⅱ(전량수출용)") < variants.index("제이스고려로얄샷ii(전량수출용)")
    assert dict(name_variants("아스피린5㎎정"))["아스피린5㎎정"] is False


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


def test_narrow_by_manufacturer_only_when_input_names_one_maker():
    from app.llm.v2.names import narrow_by_manufacturer

    a = {"product_key": "1", "manufacturer": "고려인삼과학주식회사"}
    b = {"product_key": "2", "manufacturer": "(주)케이지앤에프"}
    c = {"product_key": "3", "manufacturer": None}
    assert narrow_by_manufacturer("약 (고려인삼과학주식회사)", [a, b]) == [a]
    assert narrow_by_manufacturer("약 ((주)케이지앤에프)", [a, b]) == [b]
    assert narrow_by_manufacturer("약 케이지앤에프", [a, b]) == [b]
    assert narrow_by_manufacturer("약", [a, b]) == [a, b]  # 제조사 없음 → 임의로 고르지 않는다
    assert narrow_by_manufacturer("약 고려인삼과학주식회사 케이지앤에프", [a, b]) == [a, b]  # 둘 다 적었으면 좁히지 않는다
    assert narrow_by_manufacturer("약 (모르는회사)", [a, b, c]) == [a, b, c]
    assert narrow_by_manufacturer("약 (고려인삼과학주식회사)", [a]) == [a]



def test_unit_spellings_are_tried_right_after_original():
    from app.llm.v2.names import unit_spellings

    variants = [text for text, _ in name_variants("타이레놀정500밀리그램")]
    assert variants[:2] == ["타이레놀정500밀리그램", "타이레놀정500밀리그람"]
    assert dict(name_variants("타이레놀정500밀리그램"))["타이레놀정500밀리그람"] is False  # 뜻이 같아 근사 일치가 아니다
    assert "타이레놀500밀리그람" in unit_spellings("타이레놀500mg") and "타이레놀500밀리그램" in unit_spellings("타이레놀500mg")
    assert unit_spellings("타이레놀") == [] and unit_spellings("mg정") == []

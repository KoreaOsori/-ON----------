from app.llm.v3.textcut import cut_at_sentence, drop_unfinished_tail


def test_cut_at_sentence_keeps_short_text():
    assert cut_at_sentence("짧아요.", 100) == ("짧아요.", False)


def test_cut_at_sentence_cuts_on_boundary():
    text = "첫 문장이에요. 둘째 문장이에요. 셋째 문장이에요."
    cut, was_cut = cut_at_sentence(text, 25)
    assert was_cut and cut == "첫 문장이에요. 둘째 문장이에요."


def test_cut_at_sentence_falls_back_to_limit_without_boundary():
    cut, was_cut = cut_at_sentence("가" * 100, 30)
    assert was_cut and cut == "가" * 30


def test_drop_unfinished_tail_removes_partial_sentence():
    text = "첫 문장이에요. 둘째 문장이에요. 셋째는 이렇게 시작해서"
    assert drop_unfinished_tail(text) == "첫 문장이에요. 둘째 문장이에요."


def test_drop_unfinished_tail_removes_partial_list_line():
    text = "주의사항은 다음과 같아요.\n- 첫째 항목이에요.\n- 둘째 항목은 이렇"
    assert drop_unfinished_tail(text) == "주의사항은 다음과 같아요.\n- 첫째 항목이에요."


def test_drop_unfinished_tail_keeps_finished_text_and_avoids_deleting_most():
    assert drop_unfinished_tail("끝났어요.  ") == "끝났어요."
    assert drop_unfinished_tail("가" * 50 + "첫 문장이에요. 시작") == "가" * 50 + "첫 문장이에요."
    long_unfinished = "이어지는 설명" * 20
    assert drop_unfinished_tail(long_unfinished) == long_unfinished

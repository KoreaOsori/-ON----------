"""문장·문단 경계에서 글을 자르는 도구 (도구 결과 줄이기와 max_tokens 로 잘린 답변 정리에 쓴다)."""
import re

# 문장 끝 기호(마침표·물음표·느낌표 등) 뒤가 공백/줄바꿈/닫는 문자/문자열 끝인 위치
_SENTENCE_END = re.compile(r"[.!?。…](?=[\s)\"'’”\]*]|$)")


def cut_at_sentence(text: str, limit: int) -> tuple[str, bool]:
    """limit 글자 안에서 가장 늦은 문장 끝에서 자른다. (잘린 글, 잘렸는지). 경계가 앞쪽 절반에도 없으면 limit 에서 자른다."""
    if len(text) <= limit:
        return text, False
    head = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    newline = head.rfind("\n")
    cut = max(ends[-1] if ends else 0, newline)
    if cut < limit // 2:
        cut = limit
    return head[:cut].rstrip(), True


def drop_unfinished_tail(text: str) -> str:
    """max_tokens 로 중간에 끊긴 답변의 마지막 미완성 문장(줄)을 지운다. 지울 만한 경계가 없으면 그대로 둔다."""
    stripped = text.rstrip()
    if not stripped:
        return stripped
    if _SENTENCE_END.search(stripped[-1:]):
        return stripped  # 이미 문장 끝으로 끝난다
    ends = [m.end() for m in _SENTENCE_END.finditer(stripped)]
    newline = stripped.rfind("\n")
    cut = max(ends[-1] if ends else 0, newline)
    if cut < len(stripped) // 3:
        return stripped  # 대부분이 사라지면 자르지 않는다
    return stripped[:cut].rstrip()

import re

CHUNKING_VERSION = "characters-v1"


def normalize(text):
    return re.sub(r"[ \t]+", " ", str(text or "").replace("\r\n", "\n")).strip()


def split_text(text, max_chars=1800, overlap=150):
    """Character budget (not token count). Prefer paragraph/sentence boundaries."""
    if max_chars < 100 or not 0 <= overlap < max_chars // 2:
        raise ValueError("청크 크기는 100 이상, 중첩은 크기의 절반 미만이어야 합니다.")
    text = normalize(text)
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + max_chars // 2, end),
                           text.rfind(". ", start + max_chars // 2, end))
            if boundary >= 0:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end == len(text):
            break
        start = max(start + 1, end - overlap)

"""DUR 품목 규칙(제품별) → DUR 성분 규칙(성분별) 연결.

품목 규칙에는 성분 규칙 번호(dur_seq)가 없어서(효능군중복 제외) 내용으로 맞춘다. 단계마다 후보를 좁히고,
하나로 좁혀지면 멈춘다. 2026-10-13 스냅샷에서 34,865행 전부 연결됨 (docs/silver_decisions.md G장).

  1. 성분 코드
  2. 복합제 조합 (노인주의 품목은 mix_ingr 에 D코드가 아니라 M코드가 들어 있어 단일/복합 구분으로 비교)
  3. 고시일
  4. 금기 내용 (품목 데이터에서 줄바꿈이 빠져 있어 공백·줄바꿈을 무시하고 비교)
  5. 내용이 같은 중복 규칙 → 하나로 확정
  6. 제형 정확 일치
  7. 제형 분류 (제품은 '나정', 규칙은 '정제'처럼 표기 단위가 다름)
  8. 남은 후보의 값(등급·연령 기준 등)이 모두 같으면 확정, 다르면 '조건별 복수' (예: 적응증별로 등급이 다른 규칙)
"""

import re

# (키워드, 분류) — 위에서부터 먼저 맞는 것을 쓴다
FORM_GROUPS = [
    ("주사", "주사"), ("좌제", "좌제"), ("서방", "서방"), ("캡슐", "캡슐"), ("시럽", "시럽"), ("과립", "과립·산"),
    ("산제", "과립·산"), ("정", "정제"), ("액", "액제"), ("겔", "외용"), ("크림", "외용"), ("연고", "외용"),
    ("첩부", "외용"), ("필름", "필름"),
]

LINKED = "확정"
MULTIPLE = "조건별 복수"
UNLINKED = "연결 안 됨"


def _codes(values):
    return tuple(sorted(values or []))


def _no_space(text):
    return re.sub(r"\s+", "", text or "")


def _form_group(token):
    for keyword, group in FORM_GROUPS:
        if keyword in token:
            return group
    return token


def _form_groups(text, sep, is_item=False):
    groups = set()
    for token in (t.strip() for t in (text or "").split(sep)):
        if token:
            groups.add(_form_group(token))
            if is_item and "서방" in token and "정" in token:  # 서방정도 정제다 (서방정 규칙이 따로 없으면 정제 규칙 적용)
                groups.add("정제")
    return groups


def link_rule(item, rules, value_column):
    """품목 규칙 1행 → (상태, 방법, 연결된 성분 규칙 목록). rules 는 같은 유형의 유효한 성분 규칙 전체."""
    candidates = [r for r in rules if r["ingr_code"] == item["ingr_code"]]
    if not candidates:
        return UNLINKED, "성분 코드 없음", []
    uses_m_codes = any(code.startswith("M") for code in item["mix_ingr_codes"] or [])
    filters = (
        (lambda r: r["mix_type"] == item["mix_type"]) if uses_m_codes
        else (lambda r: _codes(r["mix_ingr_codes"]) == _codes(item["mix_ingr_codes"])),
        lambda r: r["notification_date"] == item["notification_date"],
        lambda r: _no_space(r["prohbt_content"]) == _no_space(item["prohbt_content"]),
    )
    for keep in filters:
        if len(candidates) == 1:
            break
        narrowed = [r for r in candidates if keep(r)]
        if not narrowed:
            return UNLINKED, "조건 불일치", []
        candidates = narrowed
    if len(candidates) == 1:
        return LINKED, "단일", candidates

    def signature(rule):
        return rule.get("form_name"), rule.get("remark"), rule.get(value_column) if value_column else None

    if len({signature(r) for r in candidates}) == 1:
        return LINKED, "중복 규칙", candidates
    item_form = item.get("form_name") or ""
    exact = [r for r in candidates if r.get("form_name") is None or item_form in r["form_name"].split("/")]
    if exact and len({signature(r) for r in exact}) == 1:
        return LINKED, "제형", exact
    item_groups = _form_groups(item_form, ",", is_item=True)
    grouped = [r for r in candidates if r.get("form_name") is None or _form_groups(r["form_name"], "/") & item_groups]
    if grouped and len({signature(r) for r in grouped}) == 1:
        return LINKED, "제형 분류", grouped
    remaining = exact or grouped or candidates
    if value_column is None or len({r.get(value_column) for r in remaining}) == 1:
        return LINKED, "값 동일", remaining
    return MULTIPLE, "값이 다른 규칙", remaining

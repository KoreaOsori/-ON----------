"""병용금기 RDS 읽기: 데이터 파이프라인이 적재하는 gold.drug_contraindication 을 직접 조회한다.

SQLite 인덱스(contra_store.ContraStore)와 같은 모양의 저장소다. 도구(contra_tool)는 `lookup_with_snapshot(reader, seqs)` 만 부른다.

- 읽기만 한다: 검색 DB 와 같은 읽기 전용 트랜잭션(Reader)으로 SELECT 만 실행하고, 모든 값은 파라미터로 바인딩한다.
- 키는 item_seq(품목기준코드) 문자열이며 product_key 'drug:<item_seq>' 에서 접두어를 뗀 값이다.
- 테이블 구조(2026-10 EC2 에서 확인): item_seq, mixture_item_seq, basis('품목 DUR' | '성분 규칙'), ingr_names/mixture_ingr_names(배열),
  prohbt_content, remark, notification_date. 한 쌍이 양방향(A,B 와 B,A)으로 모두 저장돼 있어 item_seq=앞 제품, mixture_item_seq=뒤 제품
  으로 한 번 조회하면 된다. 혹시 한쪽만 있는 쌍을 위해 비어 있으면 반대 방향도 조회한다.
- '성분 규칙'은 성분 단위 규칙이 제품 쌍으로 풀려 들어온 것이라 SQLite 인덱스(품목 DUR 만 변환)보다 범위가 넓다. 결과에 규칙 종류를 함께 적는다.
- gold 스키마는 데이터 파이프라인 소유다. 우리는 읽기만 하며, 조회가 느리면 (item_seq, mixture_item_seq) 인덱스를 그쪽에 요청한다.
"""
from itertools import combinations
from typing import Any

from app.llm.v2.contra_store import ContraRule, LookupResult, PairCheck

TABLE = "gold.drug_contraindication"
MAX_RULES_PER_PAIR = 20

_HAS_RULES_SQL = f"SELECT 1 AS hit FROM {TABLE} WHERE item_seq = :seq LIMIT 1"
_PAIR_SQL = (
    f"SELECT ingr_names, mixture_ingr_names, prohbt_content, remark, notification_date, basis FROM {TABLE} "
    "WHERE item_seq = :first AND mixture_item_seq = :second "
    "ORDER BY CASE WHEN basis = '품목 DUR' THEN 0 ELSE 1 END, id LIMIT :limit"
)


def _names(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None and str(v).strip())
    return str(value)


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


class RdsContraStore:
    """gold.drug_contraindication 조회기. 상태가 없어 하나를 여러 요청이 공유해도 된다."""

    def __init__(self, max_rules_per_pair: int = MAX_RULES_PER_PAIR) -> None:
        self._limit = max_rules_per_pair

    async def lookup_with_snapshot(self, reader: Any, seqs: list[str]) -> tuple[LookupResult, str | None]:
        """seqs 의 모든 조합(앞→뒤 순서)에 대한 규칙과 제품별 규칙 보유 여부. 자료 기준일은 이 테이블에 없어 None."""
        has_rules: dict[str, bool] = {}
        for seq in seqs:
            has_rules[seq] = bool(await reader.fetch(_HAS_RULES_SQL, {"seq": seq}))
        pairs: list[PairCheck] = []
        for first, second in combinations(seqs, 2):
            rows = await reader.fetch(_PAIR_SQL, {"first": first, "second": second, "limit": self._limit})
            swapped = False
            if not rows:  # 보통 양방향으로 저장돼 있지만, 한쪽만 있는 쌍도 놓치지 않는다
                rows = await reader.fetch(_PAIR_SQL, {"first": second, "second": first, "limit": self._limit})
                swapped = bool(rows)
            rules = [
                ContraRule(
                    first_names=_names(row["mixture_ingr_names"] if swapped else row["ingr_names"]),
                    second_names=_names(row["ingr_names"] if swapped else row["mixture_ingr_names"]),
                    content=_text(row["prohbt_content"]) or "(원문에 금기 내용이 비어 있습니다)",
                    remark=_text(row["remark"]),
                    form_name=None,
                    notified=_text(row["notification_date"]),
                    basis=_text(row["basis"]),
                )
                for row in rows
            ]
            if rules:
                has_rules[first] = has_rules[second] = True
            pairs.append(PairCheck(first, second, rules))
        return LookupResult(pairs, has_rules), None

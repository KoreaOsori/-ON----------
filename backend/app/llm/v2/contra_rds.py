"""병용금기 RDS 읽기: 데이터 파이프라인이 적재하는 gold.drug_contraindication 을 직접 조회한다.

SQLite 인덱스(contra_store.ContraStore)와 같은 모양의 저장소다. 도구(contra_tool)는 `lookup_with_snapshot(reader, seqs)` 만 부른다.

- 읽기만 한다: 검색 DB 와 같은 읽기 전용 트랜잭션(Reader)으로 SELECT 만 실행하고, 모든 값은 파라미터로 바인딩한다.
- 키는 item_seq(품목기준코드) 문자열이며 product_key 'drug:<item_seq>' 에서 접두어를 뗀 값이다.
- 테이블 구조(2026-10 EC2 에서 확인): item_seq, mixture_item_seq, basis('품목 DUR' | '성분 규칙'), ingr_names/mixture_ingr_names(배열),
  prohbt_content, remark, notification_date. 한 쌍이 양방향(A,B 와 B,A)으로 모두 저장돼 있어 item_seq=앞 제품, mixture_item_seq=뒤 제품
  으로 한 번 조회하면 된다. 혹시 한쪽만 있는 쌍을 위해 비어 있으면 반대 방향도 조회한다.
- '성분 규칙'은 성분 단위 규칙이 제품 쌍으로 풀려 들어온 것이라 SQLite 인덱스(품목 DUR 만 변환)보다 범위가 넓다. 결과에 규칙 종류를 함께 적는다.
- 성분 이름으로도 조회한다(제품명으로 찾을 수 없을 때 contra_tool 이 부른다): gold.drug_ingredient 로 이름→DUR 성분 코드(D코드)를 바꾸고,
  drug_contraindication 의 ingr_code/mixture_ingr_code 로 맞춘다. 성분이 낀 조합은 이 방식으로 판정하며, 조회 키는 'ingr:D000147+D000148' 모양이다.
  성분 단위라 제형 같은 제품별 조건은 반영되지 않고 복합제 규칙은 정확히 맞지 않을 수 있다(결과에 그대로 밝힌다).
- gold 스키마는 데이터 파이프라인 소유다. 우리는 읽기만 하며, 조회가 느리면 (item_seq, mixture_item_seq) 인덱스를 그쪽에 요청한다.
"""
import logging
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from app.llm.v2.contra_store import ContraRule, EfficacyOverlap, LookupResult, PairCheck
from app.llm.v2.db import safe_error_name

logger = logging.getLogger(__name__)

TABLE = "gold.drug_contraindication"
INGREDIENT_TABLE = "gold.drug_ingredient"
MAX_RULES_PER_PAIR = 20
INGREDIENT_PREFIX = "ingr:"

_HAS_RULES_SQL = f"SELECT 1 AS hit FROM {TABLE} WHERE item_seq = :seq LIMIT 1"
_PAIR_SQL = (
    f"SELECT ingr_names, mixture_ingr_names, prohbt_content, remark, notification_date, basis FROM {TABLE} "
    "WHERE item_seq = :first AND mixture_item_seq = :second "
    "ORDER BY CASE WHEN basis = '품목 DUR' THEN 0 ELSE 1 END, id LIMIT :limit"
)


_FIND_INGREDIENT_SQL = f"SELECT DISTINCT ingr_name, dur_ingr_code FROM {INGREDIENT_TABLE} WHERE ingr_name = :name LIMIT 50"
_DRUG_CODES_SQL = f"SELECT DISTINCT dur_ingr_code FROM {INGREDIENT_TABLE} WHERE item_seq = :seq AND dur_ingr_code IS NOT NULL"
_INGREDIENT_HAS_RULES_SQL = f"SELECT 1 AS hit FROM {TABLE} WHERE ingr_code = ANY(:codes) LIMIT 1"
# 성분 코드 조합별로 같은 내용(금기 내용·비고·규칙 종류)을 한 줄로 합친다. 한 방향만 읽는다(양방향 저장).
_INGREDIENT_PAIR_SQL = (
    "SELECT min(c.ingr_names[1]) AS first_name, min(c.mixture_ingr_names[1]) AS second_name, "
    "c.prohbt_content, c.remark, c.basis, min(c.notification_date) AS notification_date "
    f"FROM {TABLE} c WHERE c.ingr_code = ANY(:first_codes) AND c.mixture_ingr_code = ANY(:second_codes) "
    "GROUP BY c.ingr_code, c.mixture_ingr_code, c.prohbt_content, c.remark, c.basis "
    "ORDER BY CASE WHEN c.basis = '품목 DUR' THEN 0 ELSE 1 END, c.ingr_code, c.mixture_ingr_code, c.prohbt_content "
    "LIMIT :limit"
)

OVERLAP_TABLE = "gold.dur_ingredient_rule"
MAX_OVERLAP_ROWS = 200
# 효능군중복 규칙(단일 성분만). 같은 효능군(sers_name)에 서로 다른 성분이 여러 제품에 나뉘어 있으면 중복 주의다.
_OVERLAP_SQL = (
    f"SELECT DISTINCT sers_name, ingr_code, ingr_name FROM {OVERLAP_TABLE} "
    "WHERE caution_type = '효능군중복' AND mix_type = '단일' AND ingr_code = ANY(:codes) "
    "ORDER BY sers_name, ingr_code LIMIT :limit"
)
_ROUTE_SQL = "SELECT item_seq, route FROM gold.drug WHERE item_seq = ANY(:seqs)"
NON_ORAL_ROUTE = "경구 외"


@dataclass(frozen=True)
class IngredientMatch:
    name: str
    codes: tuple[str, ...]  # DUR 성분 코드(D코드). 이름이 같은 성분이 코드 여러 개로 나뉘면 모두


def ingredient_lookup_id(codes: tuple[str, ...] | list[str]) -> str:
    return INGREDIENT_PREFIX + "+".join(sorted(set(codes)))


def _is_ingredient(lookup_id: str) -> bool:
    return lookup_id.startswith(INGREDIENT_PREFIX)


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

    supports_ingredients = True

    def __init__(self, max_rules_per_pair: int = MAX_RULES_PER_PAIR) -> None:
        self._limit = max_rules_per_pair

    async def find_ingredient(self, reader: Any, name: str) -> tuple[IngredientMatch | None, bool]:
        """성분 이름 → (DUR 성분 코드를 가진 성분, 이름은 있으나 DUR 코드가 없는지). 이름이 정확히 같을 때만 찾는다."""
        rows = await reader.fetch(_FIND_INGREDIENT_SQL, {"name": name})
        if not rows:
            return None, False
        codes = tuple(sorted({row["dur_ingr_code"] for row in rows if row["dur_ingr_code"]}))
        if not codes:
            return None, True
        return IngredientMatch(rows[0]["ingr_name"] or name, codes), False

    async def lookup_with_snapshot(self, reader: Any, seqs: list[str]) -> tuple[LookupResult, str | None]:
        """조회 키의 모든 조합(앞→뒤 순서)에 대한 규칙과 키별 규칙 보유 여부. 자료 기준일은 이 테이블에 없어 None.

        키: 제품은 item_seq, 성분은 'ingr:D코드[+D코드]'. 둘 다 제품이면 제품 쌍(item_seq)으로, 성분이 하나라도 끼면 성분 코드로 조회한다."""
        has_rules: dict[str, bool] = {}
        for key in seqs:
            if _is_ingredient(key):
                codes = key[len(INGREDIENT_PREFIX):].split("+")
                has_rules[key] = bool(await reader.fetch(_INGREDIENT_HAS_RULES_SQL, {"codes": codes}))
            else:
                has_rules[key] = bool(await reader.fetch(_HAS_RULES_SQL, {"seq": key}))
        drug_codes: dict[str, list[str]] = {}
        pairs: list[PairCheck] = []
        for first, second in combinations(seqs, 2):
            if _is_ingredient(first) or _is_ingredient(second):
                pairs.append(await self._ingredient_pair(reader, first, second, drug_codes))
                continue
            rows = await reader.fetch(_PAIR_SQL, {"first": first, "second": second, "limit": self._limit})
            swapped = False
            if not rows:  # 보통 양방향으로 저장돼 있지만, 한쪽만 있는 쌍도 놓치지 않는다
                rows = await reader.fetch(_PAIR_SQL, {"first": second, "second": first, "limit": self._limit})
                swapped = bool(rows)
            rules = [self._rule(row, swapped) for row in rows]
            product_rules = [rule for rule in rules if rule.basis != "성분 규칙"]  # 규칙 종류가 비어 있으면 품목 단위로 본다
            if product_rules:
                # 품목 단위 병용금기가 있으면 그것만 보여 준다(성분 규칙 행은 같은 조합의 부수 정보라 섞지 않는다)
                rules, level, check = product_rules, "product", ""
            else:
                # 품목 병용금기가 없을 때만 두 제품의 성분끼리 비교해 '성분 기준 주의'를 찾는다
                rules, check = await self._with_ingredient_rules(reader, first, second, rules, drug_codes)
                level = "ingredient" if rules else "product"
            if rules:
                has_rules[first] = has_rules[second] = True
            pairs.append(PairCheck(first, second, rules, level=level, ingredient_check=check))
        # 병용금기와 별개로 같은 효능군 중복을 본다. 실패해도 병용금기 결과는 그대로 전하도록 마지막에, 오류는 삼킨다.
        overlaps = await self._overlaps(reader, seqs, drug_codes)
        return LookupResult(pairs, has_rules, overlaps), None

    @staticmethod
    def _rule(row: Any, swapped: bool, basis: str | None = None) -> ContraRule:
        return ContraRule(
            first_names=_names(row["mixture_ingr_names"] if swapped else row["ingr_names"]),
            second_names=_names(row["ingr_names"] if swapped else row["mixture_ingr_names"]),
            content=_text(row["prohbt_content"]) or "(원문에 금기 내용이 비어 있습니다)",
            remark=_text(row["remark"]),
            form_name=None,
            notified=_text(row["notification_date"]),
            basis=basis or _text(row["basis"]),
        )

    async def _with_ingredient_rules(
        self, reader: Any, first: str, second: str, existing: list[ContraRule], cache: dict[str, list[str]]
    ) -> tuple[list[ContraRule], str]:
        """제품 쌍에 품목 병용금기가 없을 때: 이미 풀려 들어온 성분 규칙(existing)에 두 제품의 성분 코드끼리 비교한 규칙을 더한다.

        성분 코드를 모르는 쪽이 있으면 비교하지 않는다(제품 단위 조회는 이미 했으므로 '확인 불가'로 바꾸지 않는다). 모든 규칙은 '성분 규칙'으로 표시한다."""
        first_codes, second_codes = await self._codes_of(reader, first, cache), await self._codes_of(reader, second, cache)
        merged = [ContraRule(**{**vars(rule), "basis": "성분 규칙"}) for rule in existing]
        logger.info("ingredient_compare codes=%d/%d existing=%d", len(first_codes), len(second_codes), len(merged))
        if not first_codes or not second_codes:
            return merged, "no_codes"
        for live in await self._ingredient_rules(reader, first_codes, second_codes, basis="성분 규칙"):
            duplicate = any(
                rule.content == live.content and rule.remark == live.remark
                and live.first_names in rule.first_names and live.second_names in rule.second_names
                for rule in merged
            )
            if not duplicate:
                merged.append(live)
        return merged[: self._limit], "compared"

    async def _ingredient_rules(self, reader: Any, first_codes: list[str], second_codes: list[str], basis: str | None = None) -> list[ContraRule]:
        rows = await reader.fetch(_INGREDIENT_PAIR_SQL, {"first_codes": first_codes, "second_codes": second_codes, "limit": self._limit})
        swapped = False
        if not rows:
            rows = await reader.fetch(_INGREDIENT_PAIR_SQL, {"first_codes": second_codes, "second_codes": first_codes, "limit": self._limit})
            swapped = bool(rows)
        return [
            ContraRule(
                first_names=_names(row["second_name"] if swapped else row["first_name"]),
                second_names=_names(row["first_name"] if swapped else row["second_name"]),
                content=_text(row["prohbt_content"]) or "(원문에 금기 내용이 비어 있습니다)",
                remark=_text(row["remark"]),
                form_name=None,
                notified=_text(row["notification_date"]),
                basis=basis or _text(row["basis"]),
            )
            for row in rows
        ]

    async def _codes_of(self, reader: Any, key: str, cache: dict[str, list[str]]) -> list[str]:
        if _is_ingredient(key):
            return key[len(INGREDIENT_PREFIX):].split("+")
        if key not in cache:
            rows = await reader.fetch(_DRUG_CODES_SQL, {"seq": key})
            cache[key] = sorted({row["dur_ingr_code"] for row in rows if row["dur_ingr_code"]})
        return cache[key]

    async def _ingredient_pair(self, reader: Any, first: str, second: str, cache: dict[str, list[str]]) -> PairCheck:
        first_codes, second_codes = await self._codes_of(reader, first, cache), await self._codes_of(reader, second, cache)
        unresolved = tuple(key for key, codes in ((first, first_codes), (second, second_codes)) if not codes)
        if unresolved:  # 성분 코드를 모르면 조회할 수 없다 — '규칙 없음'으로 오해하지 않게 따로 표시한다
            return PairCheck(first, second, [], level="ingredient", unresolved=unresolved)
        rules = await self._ingredient_rules(reader, first_codes, second_codes)
        return PairCheck(first, second, rules, level="ingredient")

    async def _overlaps(self, reader: Any, keys: list[str], cache: dict[str, list[str]]) -> list[EfficacyOverlap]:
        """조회 대상들 사이의 효능군 중복. 서로 다른 두 대상에 같은 효능군의 서로 다른 성분이 있으면 해당 효능군을 돌려준다.

        먹는 약이 아닌 제품(gold.drug.route = '경구 외')은 뺀다. 이 단계의 어떤 오류도 병용금기 결과를 막지 않는다."""
        try:
            if len(keys) < 2:
                return []
            codes_by_key = {key: await self._codes_of(reader, key, cache) for key in keys}
            product_seqs = [key for key in keys if not _is_ingredient(key) and codes_by_key[key]]
            routes: dict[str, str | None] = {}
            if product_seqs:
                routes = {row["item_seq"]: row["route"] for row in await reader.fetch(_ROUTE_SQL, {"seqs": product_seqs})}
            eligible = [key for key in keys if codes_by_key[key] and routes.get(key) != NON_ORAL_ROUTE]
            if len(eligible) < 2:
                return []
            all_codes = sorted({code for key in eligible for code in codes_by_key[key]})
            rows = await reader.fetch(_OVERLAP_SQL, {"codes": all_codes, "limit": MAX_OVERLAP_ROWS})
            series_codes: dict[str, dict[str, str]] = {}
            for row in rows:
                series_codes.setdefault(row["sers_name"], {})[row["ingr_code"]] = row["ingr_name"]
            overlaps: list[EfficacyOverlap] = []
            for series, names in series_codes.items():
                members = [(key, [code for code in codes_by_key[key] if code in names]) for key in eligible]
                members = [(key, codes) for key, codes in members if codes]
                distinct_pair = any(a != b for i, (_, ca) in enumerate(members) for _, cb in members[i + 1:] for a in ca for b in cb)
                if len(members) >= 2 and distinct_pair:
                    overlaps.append(EfficacyOverlap(series, tuple((key, ", ".join(names[c] for c in codes)) for key, codes in members)))
            return overlaps
        except Exception as exc:  # noqa: BLE001
            logger.error("효능군 중복 조회 실패: %s", safe_error_name(exc))
            return []

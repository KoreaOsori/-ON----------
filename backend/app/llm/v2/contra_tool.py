"""병용금기 확인 도구 check_contraindication (임베딩 검색이 아니라 정확 조회).

사용자가 말한 제품명 2~5개 → 검색 DB 에서 제품 하나씩 확정(product_key 'drug:<item_seq>') → 병용금기 인덱스(contra_store)에서
모든 조합을 조회 → '[출처 | A × B | 병용금기(DUR)]' 형식의 근거 문자열.

안전 규칙(코드로 강제)
- 제품이 여럿으로 갈리면(2개 이상) 임의로 고르지 않고 [확인 필요]로 되묻는다. 못 찾으면 [검색 결과 없음].
- 규칙이 없을 때 '안전하다'고 말하지 않는다: 결과 문구가 '자료에서 확인되지 않음'임을 분명히 적고, 근거 목록에는
  '병용금기 자료 조회'로만 남긴다(자료에 없는 제품·성분·조건은 판단할 수 없다).
- 금기 내용과 조건·비고는 원문 그대로 전한다. 해석·요약은 모델이 하되 원문에 없는 내용을 더하지 않도록 프롬프트가 막는다.
- 이 도구는 DB 를 읽기만 하고(검색 DB 읽기 전용 트랜잭션), 병용금기 파일도 읽기 전용으로 연다.
"""
import asyncio
import logging
import unicodedata
from typing import Any

from app.llm.v2.config import V2Settings
from app.llm.v2.contra_store import ContraStore, LookupResult
from app.llm.v2.db import ReaderFactory, safe_error_name
from app.llm.v2.names import short_name
from app.llm.v2.search import PRODUCT_KEY_PATTERN, active_run_id, find_by_key, find_products
from app.llm.v2.tools import MAX_NAME_CHARS, MAX_RESULT_CHARS, Evidence, ToolResult, _clean_str

logger = logging.getLogger(__name__)

CONTRA_TOOL_NAME = "check_contraindication"
MIN_PRODUCTS, MAX_PRODUCTS = 2, 5
MAX_RULES_SHOWN = 5


def build_contra_spec() -> dict[str, Any]:
    return {
        "name": CONTRA_TOOL_NAME,
        "description": (
            "의약품 2~5개를 함께 복용해도 되는지, 등록된 병용금기(DUR) 자료에서 조합별로 확인한다. "
            "제품명은 사용자가 말한 이름을 그대로 넣는다(괄호 안 내용을 말했다면 포함, 말하지 않았다면 추측해서 넣지 않는다). "
            "[확인 필요] 후보 중 사용자가 고른 제품은 그 product_key를 이름 대신 넣는다. "
            "건강기능식품은 이 자료로 확인할 수 없다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "minItems": MIN_PRODUCTS,
                    "maxItems": MAX_PRODUCTS,
                    "items": {"type": "string", "maxLength": MAX_NAME_CHARS},
                    "description": "함께 복용하려는 약의 제품명(또는 product_key) 목록. 예: ['와파린정', '아스피린장용정100밀리그램']",
                }
            },
            "required": ["products"],
        },
    }


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value)


class ContraindicationTool:
    """check_contraindication 실행기. 검색 DB 연결 팩토리와 병용금기 저장소를 주입받는다."""

    def __init__(self, settings: V2Settings, reader_factory: ReaderFactory, store: ContraStore) -> None:
        self._settings = settings
        self._reader_factory = reader_factory
        self._store = store

    @property
    def spec(self) -> dict[str, Any]:
        return build_contra_spec()

    # ------------------------------------------------------------------ 인자
    @staticmethod
    def _parse(arguments: Any) -> list[str]:
        if not isinstance(arguments, dict):
            raise ValueError("인자는 객체여야 합니다.")
        raw = arguments.get("products")
        if not isinstance(raw, list):
            raise ValueError("products 는 제품명 목록이어야 합니다.")
        items: list[str] = []
        for value in raw:
            text = _clean_str(value, MAX_NAME_CHARS)
            if text:
                items.append(text)
        unique = list(dict.fromkeys(item.lower() for item in items))
        if not MIN_PRODUCTS <= len(unique) <= MAX_PRODUCTS:
            raise ValueError(f"제품은 서로 다른 {MIN_PRODUCTS}~{MAX_PRODUCTS}개를 넣어야 합니다.")
        return [next(i for i in items if i.lower() == key) for key in unique]

    # ------------------------------------------------------------------ 제품 확정
    async def _resolve(self, reader: Any, run_id: str, text: str) -> tuple[dict[str, Any] | None, ToolResult | None, bool]:
        """(제품, 사용자에게 돌려줄 결과(문제가 있을 때), 근사 일치 여부)."""
        folded = _fold(text)
        if PRODUCT_KEY_PATTERN.match(folded):
            product = await find_by_key(reader, run_id, folded)
            if product is None:
                return None, ToolResult(f"[검색 결과 없음] product_key '{folded}'에 해당하는 제품이 없습니다. 제품명을 다시 확인해 달라고 안내하세요."), False
            approximate = False
        else:
            found = await find_products(reader, run_id, text, product_type="drug")
            products = found["products"]
            if found["truncated"]:
                return None, ToolResult(f"[검색 결과 없음] '{text}'과(와) 일치하는 제품이 너무 많습니다. 제품명을 더 구체적으로 알려 달라고 안내하세요."), False
            if not products:
                return None, ToolResult(f"[검색 결과 없음] '{text}'과(와) 일치하는 의약품을 찾지 못했습니다. 제품명을 다시 확인해 달라고 안내하세요."), False
            if len(products) > 1:
                shown = products[:10]
                lines = [
                    f"[확인 필요] '{text}'과(와) 일치하는 의약품이 {len(products)}개 있습니다. 임의로 고르지 말고 사용자에게 어느 제품인지 "
                    "물어보세요. 사용자가 고르면 이름 대신 그 product_key를 products 에 넣어 다시 확인하세요."
                ]
                lines += [f"- {p['product_name']} ({p['manufacturer']}) / product_key={p['product_key']}" for p in shown]
                if len(products) > len(shown):
                    lines.append(f"- …외 {len(products) - len(shown)}개")
                candidates = [{k: p[k] for k in ("product_key", "product_name", "manufacturer")} for p in products]
                return None, ToolResult("\n".join(lines), candidates=candidates), False
            product, approximate = products[0], bool(found["approximate"])
        if product["product_type"] != "drug":
            return None, ToolResult(
                f"[확인 불가] '{short_name(product['product_name'])}'은(는) 의약품이 아니라 병용금기 자료로 확인할 수 없습니다. "
                "약사·의사에게 확인하도록 안내하세요."
            ), False
        return product, None, approximate

    # ------------------------------------------------------------------ 실행
    async def run(self, arguments: Any) -> ToolResult:
        try:
            requested = self._parse(arguments)
        except ValueError as exc:
            return ToolResult(f"[인자 오류] {exc}", is_error=True)

        try:
            resolved: list[dict[str, Any]] = []
            notes: list[str] = []
            async with self._reader_factory() as reader:
                run_id = await active_run_id(reader)
                if run_id is None:
                    return ToolResult("[검색 불가] 공개된 의약품 정보가 아직 없습니다.", is_error=True)
                for text in requested:
                    product, problem, approximate = await self._resolve(reader, run_id, text)
                    if problem is not None:
                        return problem
                    assert product is not None
                    if approximate:
                        notes.append(
                            f"[참고] '{text}'과(와) 정확히 일치하는 제품이 없어 '{product['product_name']}'(으)로 확인했습니다. "
                            "답변에서 어떤 제품 기준인지 밝히세요."
                        )
                    resolved.append(product)
            keys = list(dict.fromkeys(p["product_key"] for p in resolved))
            if len(keys) < MIN_PRODUCTS:
                return ToolResult("[인자 오류] 서로 다른 제품 2개 이상이 필요합니다.", is_error=True)
            by_key = {p["product_key"]: p for p in resolved}
            seqs = [key.split(":", 1)[1] for key in keys]
            lookup = await asyncio.to_thread(self._store.lookup, seqs)
            snapshot = await asyncio.to_thread(self._store.meta, "snapshot")
        except Exception as exc:  # noqa: BLE001 - 상세 메시지는 남기지 않는다.
            logger.error("check_contraindication 실패: %s", safe_error_name(exc))
            return ToolResult("[검색 오류] 지금은 병용금기 정보를 조회할 수 없습니다.", is_error=True)

        result = format_lookup(lookup, {key.split(":", 1)[1]: by_key[key] for key in keys}, snapshot, notes)
        logger.info(
            "check_contraindication products=%d pairs=%d with_rules=%d",
            len(keys), len(lookup.pairs), sum(1 for p in lookup.pairs if p.rules),
        )
        return result


def _rule_lines(pair_rules: list, limit: int) -> list[str]:
    lines: list[str] = []
    seen: set[tuple] = set()
    shown = 0
    for rule in pair_rules:
        signature = (rule.first_names, rule.second_names, rule.content, rule.remark)
        if signature in seen:
            continue
        seen.add(signature)
        if shown >= limit:
            continue
        shown += 1
        lines.append(f"- 성분: {rule.first_names or '(미상)'} × {rule.second_names or '(미상)'}")
        lines.append(f"  금기 내용: {rule.content}")
        if rule.remark:
            lines.append(f"  조건·비고: {rule.remark}")
        if rule.form_name:
            lines.append(f"  제형: {rule.form_name}")
        if rule.notified:
            lines.append(f"  고시일: {rule.notified}")
    extra = len(seen) - shown
    if extra > 0:
        lines.append(f"- …이 밖에 같은 조합의 규칙이 {extra}건 더 있습니다.")
    return lines


def format_lookup(
    lookup: LookupResult, products_by_seq: dict[str, dict[str, Any]], snapshot: str | None, notes: list[str] | None = None
) -> ToolResult:
    """조회 결과 → LLM 에 줄 근거 문자열 + 근거 목록(Evidence)."""
    names = {seq: short_name(p["product_name"]) for seq, p in products_by_seq.items()}
    blocks: list[str] = list(notes or [])
    blocks.append(f"[병용금기 확인 | 자료 기준일 {snapshot or '알 수 없음'} | 확인한 제품 {len(names)}개]")
    evidence: list[Evidence] = []
    for pair in lookup.pairs:
        label = f"{names[pair.first]} × {names[pair.second]}"
        if pair.rules:
            lines = [f"■ {label} — 병용금기 규칙 있음", f"[출처 | {label} | 병용금기(DUR)]"]
            lines += _rule_lines(pair.rules, MAX_RULES_SHOWN)
            evidence.append(Evidence(label, "", "contraindication", 1, display=label))
        else:
            missing = [names[s] for s in (pair.first, pair.second) if not lookup.has_rules.get(s)]
            coverage = (
                f" (이 자료에 병용금기 규칙이 하나도 등록돼 있지 않은 제품: {', '.join(missing)})" if missing else ""
            )
            lines = [
                f"■ {label} — 병용금기 규칙 없음",
                f"[출처 | {label} | 병용금기 자료 조회]",
                "등록된 병용금기 자료에서 이 조합의 규칙을 찾지 못했습니다" + coverage + ". 이것은 함께 복용해도 안전하다는 뜻이 아닙니다"
                "(자료에 없는 제품·성분이거나, 병용금기가 아닌 다른 주의사항이 있을 수 있습니다). "
                "'확인되지 않았다'고만 말하고 약사·의사 확인을 권하세요.",
            ]
            evidence.append(Evidence(label, "", "contraindication_none", 1, display=label))
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n…(길이 제한으로 이하 생략)"
    return ToolResult(text, evidence)

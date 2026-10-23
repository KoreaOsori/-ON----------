"""병용금기 확인 도구 check_contraindication (임베딩 검색이 아니라 정확 조회).

사용자가 말한 제품명 2~5개 → 검색 DB 에서 제품 하나씩 확정(product_key 'drug:<item_seq>' 또는 'health_food:<id>') →
의약품끼리는 병용금기 인덱스(contra_store)에서 모든 조합을 조회 → '[출처 | A × B | 병용금기(DUR)]' 형식의 근거 문자열.
제품명으로 찾을 수 없는 이름은 성분 이름으로 한 번 더 찾는다(RDS 저장소일 때만): 성분이 낀 조합은 DUR 성분 코드로 조회하고,
결과에 "성분 기준 조회라 제형 등 제품별 조건이 반영되지 않았다"는 점을 코드가 적는다.
건강기능식품이 섞인 조합은 정식 병용금기 판정을 하지 않고, 그 제품의 섭취 주의사항(precautions)만 전부 보여 준다
(v1 service.py 와 같은 정책: 상호작용 유무를 추정하지 않는다).

안전 규칙(코드로 강제)
- 제품이 여럿으로 갈리면(2개 이상) 임의로 고르지 않고 [확인 필요]로 되묻는다. 못 찾으면 [검색 결과 없음].
- 건강기능식품 주의사항은 문단 단위로만 담는다(문장 중간에서 자르지 않음). 길어서 못 담으면 생략했다는 안내를 결과에 적는다.
- 규칙이 없을 때 '안전하다'고 말하지 않는다: 결과 문구가 '자료에서 확인되지 않음'임을 분명히 적고, 근거 목록에는
  '병용금기 자료 조회'로만 남긴다(자료에 없는 제품·성분·조건은 판단할 수 없다).
- 금기 내용과 조건·비고는 원문 그대로 전한다. 해석·요약은 모델이 하되 원문에 없는 내용을 더하지 않도록 프롬프트가 막는다.
- 이 도구는 DB 를 읽기만 하고(검색 DB 읽기 전용 트랜잭션), 병용금기 파일도 읽기 전용으로 연다.
"""
import logging
from dataclasses import replace
import unicodedata
from itertools import combinations
from typing import Any

from app.llm.v3.config import V3Settings
from app.llm.v3.contra_rds import ingredient_lookup_id
from app.llm.v3.grounded_answer import interaction_blocks
from app.llm.v3.contra_store import LookupResult
from app.llm.v3.db import ReaderFactory, safe_error_name
from app.llm.v3.names import short_name
from app.llm.v3.search import PRODUCT_KEY_PATTERN, active_run_id, fetch_section_texts, find_by_key, find_products
from app.llm.v3.tools import MAX_NAME_CHARS, MAX_RESULT_CHARS, Evidence, ToolResult, _clean_str

logger = logging.getLogger(__name__)

CONTRA_TOOL_NAME = "check_contraindication"
MIN_PRODUCTS, MAX_PRODUCTS = 2, 5
MAX_RULES_SHOWN = 5
FOOD_TOTAL_CHARS = 6000  # 건강기능식품 주의사항 전체 글자 예산(제품 수로 나눔)
MIN_FOOD_CHARS = 1500  # 제품당 최소 예산. 첫 문단은 예산과 상관없이 항상 담는다
FOOD_LABEL = "건강기능식품"
INGREDIENT_TYPE = "ingredient"
INGREDIENT_CAVEAT = (
    "[성분 기준 조회] 성분 이름이 낀 조합이나 성분 기준 주의는 DUR 성분 코드로 조회했습니다. 제형 등 제품별 조건은 반영되지 않았고 복합제 규칙은 정확히 "
    "맞지 않을 수 있습니다. 답변에서 이 점을 밝히고, 특정 제품 기준의 정확한 확인은 제품명으로 다시 물어보거나 약사·의사에게 확인하도록 안내하세요."
)


def build_contra_spec() -> dict[str, Any]:
    return {
        "name": CONTRA_TOOL_NAME,
        "description": (
            "의약품 2~5개를 함께 복용해도 되는지, 등록된 병용금기(DUR) 자료에서 조합별로 확인한다. "
            "제품명은 사용자가 말한 이름을 그대로 넣는다(괄호 안 내용을 말했다면 포함, 말하지 않았다면 추측해서 넣지 않는다). "
            "사용자가 제품이 아니라 성분 이름(예: 아세트아미노펜)을 말했으면 그 이름을 그대로 넣는다. "
            "건강기능식품이 섞여 있으면 병용금기 판정은 할 수 없고, 그 제품의 섭취 주의사항만 보여 준다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "minItems": MIN_PRODUCTS,
                    "maxItems": MAX_PRODUCTS,
                    "items": {"type": "string", "maxLength": MAX_NAME_CHARS},
                    "description": "함께 복용하려는 약·건강기능식품의 제품명(또는 성분 이름) 목록. 예: ['와파린정', '아스피린장용정100밀리그램']",
                }
            },
            "required": ["products"],
        },
    }


def _lookup_id(product: dict[str, Any]) -> str:
    """병용금기 저장소의 조회 키: 제품은 item_seq, 성분은 'ingr:D코드[+D코드]'."""
    if product["product_type"] == INGREDIENT_TYPE:
        return ingredient_lookup_id(product["codes"])
    return product["product_key"].split(":", 1)[1]


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value)


class ContraindicationTool:
    """check_contraindication 실행기. 검색 DB 연결 팩토리와 병용금기 저장소를 주입받는다.

    저장소는 `async lookup_with_snapshot(reader, seqs) -> (LookupResult, 자료 기준일 | None)` 만 있으면 된다
    (ContraStore=SQLite 파일, RdsContraStore=RDS gold.drug_contraindication)."""

    def __init__(self, settings: V3Settings, reader_factory: ReaderFactory, store: Any) -> None:
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
    async def _resolve(self, reader: Any, run_id: str, text: str) -> tuple[dict[str, Any] | None, ToolResult | None, bool, str]:
        """(제품, 사용자에게 돌려줄 결과(문제가 있을 때), 근사 일치 여부, 성분 이름으로 넘어갈 수 있는 상황).

        마지막 값: "missing"=이름으로 아무 제품도 못 찾음, "ambiguous"=정확히 일치하는 제품은 없고 앞부분·일부만 맞는 제품이 여럿(또는 너무 많음),
        ""=성분으로 넘어가면 안 되는 경우(product_key 입력, 이름이 정확히 같은 제품이 여럿, 그 밖의 문제)."""
        folded = _fold(text)
        if PRODUCT_KEY_PATTERN.match(folded):
            product = await find_by_key(reader, run_id, folded)
            if product is None:
                return None, ToolResult(f"[검색 결과 없음] product_key '{folded}'에 해당하는 제품이 없습니다. 제품명을 다시 확인해 달라고 안내하세요."), False, ""
            approximate = False
        else:
            found = await find_products(reader, run_id, text)
            products = found["products"]
            if found["truncated"]:
                return None, ToolResult(f"[검색 결과 없음] '{text}'과(와) 일치하는 제품이 너무 많습니다. 제품명을 더 구체적으로 알려 달라고 안내하세요."), False, ("" if found["mode"] == "exact" else "ambiguous")
            if not products:
                return None, ToolResult(f"[검색 결과 없음] '{text}'과(와) 일치하는 의약품을 찾지 못했습니다. 제품명을 다시 확인해 달라고 안내하세요."), False, "missing"
            if len(products) > 1:
                shown = products[:10]
                lines = [
                    f"[확인 필요] '{text}'과(와) 일치하는 의약품이 {len(products)}개 있습니다. 임의로 고르지 말고 사용자에게 해당하는 제품을 "
                    "제품명(제조사 포함)으로 다시 입력해 질문해 달라고 안내하세요."
                ]
                lines += [
                    f"- {'[건강기능식품] ' if p['product_type'] == 'health_food' else ''}{p['product_name']} ({p['manufacturer']})"
                    for p in shown
                ]
                if len(products) > len(shown):
                    lines.append(f"- …외 {len(products) - len(shown)}개")
                candidates = [{k: p[k] for k in ("product_key", "product_name", "manufacturer")} for p in products]
                return None, ToolResult("\n".join(lines), candidates=candidates), False, ("" if found["mode"] == "exact" else "ambiguous")
            product, approximate = products[0], bool(found["approximate"])
        if product["product_type"] not in ("drug", "health_food"):
            return None, ToolResult(
                f"[확인 불가] '{short_name(product['product_name'])}'은(는) 이 도구로 확인할 수 없는 종류입니다. "
                "약사·의사에게 확인하도록 안내하세요."
            ), False, ""
        return product, None, approximate, ""

    async def _resolve_ingredient(self, reader: Any, text: str) -> tuple[dict[str, Any] | None, ToolResult | None]:
        """제품으로 못 찾은 이름을 성분 이름으로 찾는다. (성분 항목, 안내 결과). 둘 다 None 이면 성분으로도 없다."""
        finder = getattr(self._store, "find_ingredient", None)
        if finder is None:  # SQLite 저장소는 성분 조회를 지원하지 않는다
            return None, None
        match, without_code = await finder(reader, _fold(text).strip())
        if match is not None:
            item = {
                "product_key": f"{INGREDIENT_TYPE}:{'+'.join(match.codes)}",
                "product_name": f"{match.name}(성분)",
                "manufacturer": "",
                "product_type": INGREDIENT_TYPE,
                "codes": match.codes,
            }
            return item, None
        if without_code:
            return None, ToolResult(
                f"[확인 불가] '{text}'은(는) 성분 이름으로는 있지만 DUR 성분 코드가 없어 병용금기를 확인할 수 없습니다. 약사·의사에게 확인하도록 안내하세요."
            )
        return None, None

    # ------------------------------------------------------------------ 실행
    async def run(self, arguments: Any) -> ToolResult:
        try:
            requested = self._parse(arguments)
        except ValueError as exc:
            return ToolResult(f"[인자 오류] {exc}", is_error=True)

        try:
            resolved: list[dict[str, Any]] = []
            notes: list[str] = []
            precautions: dict[str, dict[str, Any]] = {}
            async with self._reader_factory() as reader:
                run_id = await active_run_id(reader)
                if run_id is None:
                    return ToolResult("[검색 불가] 공개된 의약품 정보가 아직 없습니다.", is_error=True)
                problems: list[ToolResult] = []  # 제품마다 확인하고 문제를 모아 한 번에 알린다(첫 문제에서 멈추면 나머지 제품을 모른다)
                for text in requested:
                    product, problem, approximate, fallback = await self._resolve(reader, run_id, text)
                    if problem is not None and fallback:
                        # 이름이 정확히 같은 제품이 없고(없거나, 앞부분·일부만 맞는 제품이 여럿) 성분 이름과는 정확히 같으면 성분으로 확인한다.
                        # 예: '케토코나졸'은 '케토코나졸크림', '더마졸정(케토코나졸)'… 수십 개 제품에 걸리지만 사용자는 성분을 말한 것이다.
                        ingredient, ingredient_problem = await self._resolve_ingredient(reader, text)
                        if ingredient is not None:
                            notes.append(
                                f"[참고] '{text}'은(는) 정확히 일치하는 제품명이 없고 성분 이름과 일치해 성분 이름으로 확인했습니다. 답변에서 성분 기준 확인임을 밝히세요."
                            )
                            resolved.append(ingredient)
                            continue
                        if ingredient_problem is not None and fallback == "missing":
                            problems.append(replace(ingredient_problem, requested=text))
                            continue
                        if fallback == "missing":
                            problems.append(ToolResult(problem.text, missing=[text], requested=text))
                            continue
                    if problem is not None:
                        problems.append(replace(problem, requested=text))
                        continue
                    assert product is not None
                    if approximate:
                        notes.append(
                            f"[참고] '{text}'과(와) 정확히 일치하는 제품이 없어 '{product['product_name']}'(으)로 확인했습니다. "
                            "답변에서 어떤 제품 기준인지 밝히세요."
                        )
                    resolved.append(product)
                if problems:
                    return _combine_problems(problems, resolved)
                keys = list(dict.fromkeys(p["product_key"] for p in resolved))
                if len(keys) < MIN_PRODUCTS:
                    return ToolResult("[인자 오류] 서로 다른 제품 2개 이상이 필요합니다.", is_error=True)
                by_key = {p["product_key"]: p for p in resolved}
                for key in keys:
                    if by_key[key]["product_type"] == "health_food":  # 같은 읽기 전용 트랜잭션에서 한 번에 읽는다
                        if hasattr(self._store, "compare_products"):
                            rows = await reader.fetch(
                                "SELECT iftkn_atnt_matr_cn FROM gold.health_food WHERE prdlst_report_no=:id",
                                {"id": key.split(":", 1)[1]},
                            )
                            precautions[key] = {"chunks": [r["iftkn_atnt_matr_cn"] for r in rows if r.get("iftkn_atnt_matr_cn")], "truncated": False}
                        else:
                            precautions[key] = await fetch_section_texts(reader, run_id, key, "precautions")
                drug_keys = [key for key in keys if by_key[key]["product_type"] in ("drug", INGREDIENT_TYPE)]
                lookup = snapshot = None
                gold_checks = None
                if len(drug_keys) >= 2:  # 의약품(또는 성분)이 둘 이상일 때만 병용금기 자료를 조회한다(RDS 저장소도 같은 읽기 전용 트랜잭션을 쓴다)
                    if hasattr(self._store, "compare_products") and all(by_key[k]["product_type"] == "drug" for k in drug_keys):
                        gold_checks = await self._store.compare_products(reader, [by_key[k] for k in drug_keys])
                    else:
                        lookup, snapshot = await self._store.lookup_with_snapshot(reader, [_lookup_id(by_key[key]) for key in drug_keys])
        except Exception as exc:  # noqa: BLE001 - 상세 메시지는 남기지 않는다.
            logger.error("check_contraindication 실패: %s", safe_error_name(exc))
            return ToolResult("[검색 오류] 지금은 병용금기 정보를 조회할 수 없습니다.", is_error=True)

        result = format_combination(keys, by_key, lookup, precautions, snapshot, notes)
        if gold_checks is not None:
            blocks = interaction_blocks({"products": resolved, "checks": gold_checks})
            instruction = (
                "[Python 판정 결과] 아래 제품쌍별 판정·비교 범위·원문 조건을 유지하세요. "
                "품목 금기, 성분 기준 주의, 동일 성분 중복은 서로 다릅니다. "
                "비교 불가를 규칙 없음으로 바꾸거나 모든 성분을 비교했다고 말하지 마세요. "
                "동일한 결과는 묶어서 짧게 설명하되 다른 결과나 예외를 생략하지 마세요."
            )
            gold_evidence = [Evidence(" × ".join(c["pair_explanation"]["products"]), "", "interaction_check", 1) for c in gold_checks]
            # format_combination emits notes only when a food/legacy lookup exists.
            identity_notes = notes if not precautions else []
            result = ToolResult("\n\n".join([*identity_notes, instruction, *blocks, result.text]), gold_evidence + result.evidence)
        logger.info(
            "check_contraindication products=%d drug_pairs=%d with_rules=%d foods=%d",
            len(keys), len(gold_checks) if gold_checks is not None else len(lookup.pairs) if lookup else 0,
            sum(bool(c['rules'] or c['ingredient_matches']) for c in gold_checks) if gold_checks is not None
            else sum(1 for p in lookup.pairs if p.rules) if lookup else 0,
            len(precautions),
        )
        return result


def _combine_problems(problems: list[ToolResult], resolved: list[dict] | None = None) -> ToolResult:
    """V3는 모든 미확정 제품과 확인된 제품을 구분한다. 이전 저장소 호출도 지원한다."""
    if resolved is not None:
        from app.llm.v3.prompts import build_resolution_answer
        return ToolResult(
            "\n\n".join(p.text for p in problems) + "\n\n제품을 모두 확정하지 못해 병용금기는 확인하지 않았습니다.",
            candidates=[c for p in problems for c in p.candidates],
            missing=[n for p in problems for n in p.missing],
            clarification=build_resolution_answer(resolved, problems),
        )
    if len(problems) == 1:
        return problems[0]
    candidates = next((p.candidates for p in problems if p.candidates), [])
    missing = [name for p in problems for name in p.missing]
    text = "\n\n".join(p.text for p in problems)
    if len(problems) > 1:
        text += "\n\n제품을 모두 확정하지 못해 병용금기는 확인하지 않았습니다."
    return ToolResult(
        text,
        candidates=list(candidates),
        missing=missing,
        other_problem=any(not p.candidates and not p.missing for p in problems),
    )


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
        if rule.basis:
            lines.append(f"  규칙 종류: {rule.basis}")
    extra = len(seen) - shown
    if extra > 0:
        lines.append(f"- …이 밖에 같은 조합의 규칙이 {extra}건 더 있습니다.")
    return lines


def _ingredient_only(rules: list) -> bool:
    """모든 규칙이 '성분 규칙'(성분 단위 주의)인가. 품목 DUR 이 하나라도 있거나 규칙 종류를 모르면(SQLite) 금기로 본다."""
    return bool(rules) and all(rule.basis == "성분 규칙" for rule in rules)


def format_lookup(
    lookup: LookupResult, products_by_seq: dict[str, dict[str, Any]], snapshot: str | None, notes: list[str] | None = None
) -> ToolResult:
    """조회 결과 → LLM 에 줄 근거 문자열 + 근거 목록(Evidence)."""
    names = {seq: short_name(p["product_name"]) for seq, p in products_by_seq.items()}
    blocks: list[str] = list(notes or [])
    when = f"자료 기준일 {snapshot} | " if snapshot else ""
    blocks.append(f"[병용금기 확인 | {when}확인한 제품 {len(names)}개]")
    if any(pair.level == "ingredient" for pair in lookup.pairs):
        blocks.append(INGREDIENT_CAVEAT)
    evidence: list[Evidence] = []
    for pair in lookup.pairs:
        label = f"{names[pair.first]} × {names[pair.second]}"
        if pair.unresolved:
            who = ", ".join(names[key] for key in pair.unresolved)
            blocks.append(
                f"■ {label} — [확인 불가] 성분 코드를 찾지 못한 제품({who})이 있어 성분 단위로는 확인하지 못했습니다. "
                "병용금기 규칙이 없다는 뜻이 아닙니다. 약사·의사에게 확인하도록 안내하세요."
            )
            continue
        if pair.rules and _ingredient_only(pair.rules):
            # 성분 규칙만 있는 조합: 식약처가 제품에 적용한 품목 단위 금기와 구분해 '성분 기준 주의'로 전한다.
            lines = [f"■ {label} — 성분 기준 주의 규칙 있음(품목 단위 병용금기는 아님)", f"[출처 | {label} | 병용 주의(성분 기준)]"]
            lines += _rule_lines(pair.rules, MAX_RULES_SHOWN)
            lines.append(
                "안내: 이 조합은 성분 단위 규칙으로 등록된 주의입니다. '병용금기'라고 단정하지 말고 "
                "'성분 기준으로 주의가 필요한 조합으로 등록돼 있다'고 전하세요."
            )
            evidence.append(Evidence(label, "", "contraindication_ingredient", 1, display=label))
        elif pair.rules:
            lines = [f"■ {label} — 병용금기 규칙 있음", f"[출처 | {label} | 병용금기(DUR)]"]
            lines += _rule_lines(pair.rules, MAX_RULES_SHOWN)
            evidence.append(Evidence(label, "", "contraindication", 1, display=label))
        else:
            missing = [names[s] for s in (pair.first, pair.second) if not lookup.has_rules.get(s)]
            coverage = (
                f" (이 자료에 병용금기 규칙이 하나도 등록돼 있지 않은 제품: {', '.join(missing)})" if missing else ""
            )
            scope = {
                "compared": " 품목 단위와 성분(DUR 성분 코드) 기준 모두 비교했습니다.",
                "no_codes": " 성분 코드를 찾지 못한 제품이 있어 성분 기준 비교는 하지 못했고 품목 단위로만 확인했습니다.",
            }.get(pair.ingredient_check, "")
            lines = [
                f"■ {label} — 병용금기 규칙 없음",
                f"[출처 | {label} | 병용금기 자료 조회]",
                "등록된 병용금기 자료에서 이 조합의 규칙을 찾지 못했습니다." + scope + coverage + " 이것은 함께 복용해도 안전하다는 뜻이 아닙니다"
                "(자료에 없는 제품·성분이거나, 병용금기가 아닌 다른 주의사항이 있을 수 있습니다). "
                "'확인되지 않았다'고만 말하고 약사·의사 확인을 권하세요.",
            ]
            evidence.append(Evidence(label, "", "contraindication_none", 1, display=label))
        blocks.append("\n".join(lines))
    for overlap in lookup.overlaps:
        who = ", ".join(f"{names[key]}({ingredients})" for key, ingredients in overlap.members if key in names)
        label = " × ".join(names[key] for key, _ in overlap.members if key in names)
        blocks.append(
            "\n".join([
                f"■ {label} — 효능군 중복 주의 규칙 있음(병용금기는 아님)",
                f"[출처 | {label} | 효능군 중복 주의(성분 기준)]",
                f"- 같은 계열: {overlap.series}",
                f"  해당 제품(성분): {who}",
                "안내: 병용금기가 아니라 같은 계열의 서로 다른 성분이 겹친다는 중복 주의입니다. '병용금기'라고 하지 말고 "
                "'같은 계열 약이라 겹쳐 드시면 중복될 수 있다'고 전하세요. 먹는 약만 비교했고 용량·제형 조건은 반영되지 않았습니다.",
            ])
        )
        evidence.append(Evidence(label, "", "efficacy_overlap", 1, display=label))
    text = "\n\n".join(blocks)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n…(길이 제한으로 이하 생략)"
    return ToolResult(text, evidence)


def format_foods(
    keys: list[str], by_key: dict[str, dict[str, Any]], precautions: dict[str, dict[str, Any]], notes: list[str] | None = None
) -> ToolResult:
    """건강기능식품이 든 조합: 병용금기 판정 없이 제품별 섭취 주의사항을 문단 단위로 전부(예산 안에서) 담는다."""
    foods = [key for key in keys if by_key[key]["product_type"] == "health_food"]
    names = {key: short_name(by_key[key]["product_name"]) for key in keys}
    lines: list[str] = list(notes or [])
    lines.append(
        f"[{FOOD_LABEL} 확인] {FOOD_LABEL}이 포함된 조합은 병용금기(DUR) 자료로 판정할 수 없습니다. 아래 제품별 섭취 주의사항에 "
        "적힌 내용만 전하고, 상호작용이 있다거나 없다고 추정하지 마세요. 안전하다고 말하지 말고 약사·의사 확인을 권하세요."
    )
    for first, second in combinations(keys, 2):
        if first in foods or second in foods:
            lines.append(f"■ {names[first]} × {names[second]} — 병용금기 판정 불가({FOOD_LABEL} 포함)")

    evidence: list[Evidence] = []
    per_food = max(MIN_FOOD_CHARS, FOOD_TOTAL_CHARS // max(1, len(foods)))
    for key in foods:
        data = precautions.get(key) or {"chunks": [], "truncated": False}
        chunks: list[str] = data["chunks"]
        if not chunks:
            lines.append(f"■ {names[key]} — [확인 불가] 등록된 섭취 주의사항이 없습니다. 약사·의사에게 확인하도록 안내하세요.")
            continue
        shown: list[str] = []
        used = 0
        for chunk in chunks:  # 문단 단위로만 담는다. 첫 문단은 항상 담고, 예산을 넘기는 문단부터는 담지 않는다.
            if shown and used + len(chunk) > per_food:
                break
            shown.append(chunk)
            used += len(chunk)
        block = [f"■ {names[key]} — 등록된 섭취 주의사항", f"[출처 | {names[key]} | 주의사항]", *shown]
        if len(shown) < len(chunks) or data["truncated"]:
            block.append(
                "[참고] 주의사항이 길어 일부 문단을 생략했습니다. 모든 주의사항을 다루지는 못했다고 밝히고, "
                "제품 라벨의 섭취 방법·주의사항 원문을 확인하도록 안내하세요."
            )
        lines.append("\n".join(block))
        product = by_key[key]
        evidence.append(Evidence(product["product_name"], product.get("manufacturer") or "", "precautions", 1))
    return ToolResult("\n\n".join(lines), evidence)


def format_combination(
    keys: list[str],
    by_key: dict[str, dict[str, Any]],
    lookup: LookupResult | None,
    precautions: dict[str, dict[str, Any]],
    snapshot: str | None,
    notes: list[str] | None = None,
) -> ToolResult:
    """의약품 쌍의 병용금기 결과(있으면)와 건강기능식품 주의사항(있으면)을 한 결과로 합친다."""
    notes = list(notes or [])
    drugs_by_seq = {_lookup_id(by_key[key]): by_key[key] for key in keys if by_key[key]["product_type"] in ("drug", INGREDIENT_TYPE)}
    parts: list[str] = []
    evidence: list[Evidence] = []
    if lookup is not None:
        drug_part = format_lookup(lookup, drugs_by_seq, snapshot, notes)
        parts.append(drug_part.text)
        evidence += drug_part.evidence
        notes = []  # 이미 맨 앞에 붙었다
    if any(by_key[key]["product_type"] == "health_food" for key in keys):
        food_part = format_foods(keys, by_key, precautions, notes)
        parts.append(food_part.text)
        evidence += food_part.evidence
    return ToolResult("\n\n".join(parts), evidence)

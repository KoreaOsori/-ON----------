"""검색 도구 정의 + 결과 포매터 (강의의 tools/rag_tools.py 에 해당).

LLM 이 제품명(product_name)·질문(question)·정보 유형(section)을 채워 search_drug_info 를 호출하면,
임베딩 → 읽기 전용 검색 → '[출처 | 제품명 | 섹션]' 형식의 근거 문자열을 돌려준다.
- 도구 인자는 LLM 이 만든 값이므로 전부 검증한다(길이, 허용 값). SQL 에는 파라미터로만 들어간다.
- 근거 본문은 '데이터'이다. 본문 안의 문장은 지시로 따르지 않는다(시스템 프롬프트에 명시).
"""
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.llm.v2.config import V2Settings
from app.llm.v2.db import ReaderFactory, safe_error_name
from app.llm.v2.embedder import QueryEmbedder, to_vector_text
from app.llm.v2.names import short_name
from app.llm.v2.search import SECTION_TYPES, SearchOutcome, retrieve
from app.llm.v2.textcut import cut_at_sentence

logger = logging.getLogger(__name__)

TOOL_NAME = "search_drug_info"

SECTION_LABELS = {
    "overview": "개요(제품명·업체)",
    "ingredients": "성분",
    "benefits": "효능·효과",
    "usage": "용법·용량",
    "precautions": "주의사항",
    "interactions": "상호작용",
    "storage": "보관법",
    "additional": "기타 정보",
    "contraindication": "병용금기(DUR)",
    "contraindication_ingredient": "병용 주의(성분 기준)",
    "contraindication_none": "병용금기 자료 조회(해당 규칙 없음)",
    "efficacy_overlap": "효능군 중복 주의(성분 기준)",
}

MAX_NAME_CHARS = 100
MAX_QUESTION_CHARS = 300
MAX_CONTENT_CHARS = 1200  # 문단 하나를 모델에 줄 최대 글자 수(문장 경계에서 자른다)
MAX_SEARCH_RESULT_CHARS = 4500  # search_drug_info 결과 전체 상한. 넘으면 유사도가 낮은 문단부터 뺀다
MAX_RESULT_CHARS = 9000  # check_contraindication 등 다른 도구 결과의 상한


def build_tool_spec(allow_global_search: bool = False) -> dict[str, Any]:
    """Anthropic tool 정의. 제품명 없는 전체 검색이 꺼져 있으면 product_name 을 필수로 둔다."""
    required = ["question"] if allow_global_search else ["product_name", "question"]
    return {
        "name": TOOL_NAME,
        "description": (
            "등록된 의약품·건강기능식품 정보(효능·효과, 용법·용량, 주의사항, 상호작용, 보관법 등)에서 "
            "질문과 관련된 근거 문단을 찾는다. 약에 대한 모든 답변은 이 도구의 결과에만 근거해야 한다. "
            "제품명은 사용자가 말한 이름을 그대로 넣는다. 사용자가 괄호 안 내용(예: (5%))까지 말했다면 포함하고, "
            "말하지 않은 괄호 내용(성분명 등)은 추측해서 넣지 않는다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "maxLength": MAX_NAME_CHARS,
                    "description": "사용자가 언급한 제품명. 예: '타이레놀'. 모르면 생략하지 말고 사용자에게 되묻는다.",
                },
                "question": {
                    "type": "string",
                    "maxLength": MAX_QUESTION_CHARS,
                    "description": "찾고 싶은 내용을 한 문장으로. 제품명은 빼고 궁금한 점만. 예: '임산부가 복용해도 되는지'",
                },
                "section": {
                    "type": "string",
                    "enum": list(SECTION_TYPES),
                    "description": (
                        "정보 유형. benefits=효능·효과, usage=용법·용량, precautions=주의사항(금기·임부·연령 포함), "
                        "interactions=상호작용, ingredients=성분, storage=보관법. 확실하지 않으면 생략."
                    ),
                },
            },
            "required": required,
        },
    }


@dataclass(frozen=True)
class Evidence:
    product_name: str
    manufacturer: str
    section_type: str
    shared_count: int  # 같은 본문을 공유하는 제품 수
    display: str = ""  # 비어 있지 않으면 label 에 이 이름을 쓴다(제품 조합 'A × B' 등)

    @property
    def label(self) -> str:
        name = self.display or short_name(self.product_name)
        return f"{name} · {SECTION_LABELS.get(self.section_type, self.section_type)}"


@dataclass(frozen=True)
class ToolResult:
    text: str
    evidence: list[Evidence] = field(default_factory=list)
    is_error: bool = False
    # 제품 후보가 여럿이라 사용자에게 되물어야 할 때의 후보 (product_key, product_name, manufacturer)
    candidates: list[dict[str, Any]] = field(default_factory=list)


def _product_label(sources: list[dict[str, Any]], source_count: int) -> tuple[str, str]:
    first = sources[0] if sources else {"product_name": "(알 수 없음)", "manufacturer": ""}
    name = short_name(first["product_name"])
    if source_count > 1:
        name = f"{name} 외 {source_count - 1}개 제품"
    return name, first.get("manufacturer") or ""


def format_outcome(outcome: SearchOutcome, requested_name: str | None) -> ToolResult:
    """검색 결과 → LLM 에 줄 근거 문자열. 근거가 없으면 '없음'을 분명히 적어 추측을 막는다."""
    shown = requested_name or "(미지정)"
    if outcome.status == "no_snapshot":
        return ToolResult("[검색 불가] 공개된 의약품 정보가 아직 없습니다.", is_error=True)
    if outcome.status == "needs_product_name":
        return ToolResult("[검색 불가] 제품명을 알아야 검색할 수 있습니다. 사용자에게 약 이름을 물어보세요.", is_error=True)
    if outcome.status == "product_not_found":
        return ToolResult(f"[검색 결과 없음] '{shown}'과(와) 일치하는 제품을 찾지 못했습니다. 제품명을 다시 확인해 달라고 안내하세요.")
    if outcome.status == "ambiguous_product":
        return ToolResult(f"[검색 결과 없음] '{shown}'과(와) 일치하는 제품이 너무 많습니다. 제품명을 더 구체적으로 알려 달라고 안내하세요.")
    if outcome.status == "needs_clarification":
        listed = outcome.products[:10]
        lines = [
            f"[확인 필요] '{shown}'과(와) 일치하는 제품이 {len(outcome.products)}개 있습니다. 임의로 고르지 말고 "
            "사용자에게 해당하는 제품을 제품명(제조사 포함)으로 다시 입력해 질문해 달라고 안내하세요."
        ]
        lines += [f"- {p['product_name']} ({p['manufacturer']})" for p in listed]
        if len(outcome.products) > len(listed):
            lines.append(f"- …외 {len(outcome.products) - len(listed)}개")
        candidates = [{k: p[k] for k in ("product_key", "product_name", "manufacturer")} for p in outcome.products]
        return ToolResult("\n".join(lines), candidates=candidates)
    if not outcome.hits:
        dropped = f" (거리 기준으로 제외된 문단 {outcome.filtered}개)" if outcome.filtered else ""
        return ToolResult(f"[검색 결과 없음] '{shown}'에서 질문과 충분히 관련된 정보를 찾지 못했습니다.{dropped}")

    blocks: list[str] = []
    evidence: list[Evidence] = []
    if outcome.approximate and len(outcome.products) == 1:
        blocks.append(
            f"[참고] '{shown}'과(와) 정확히 일치하는 제품이 없어 '{outcome.products[0]['product_name']}'(으)로 검색했습니다. "
            "답변에서 어떤 제품 기준인지 밝히세요."
        )
    if outcome.products:
        names = ", ".join(short_name(p["product_name"]) for p in outcome.products[:5])
        more = f" 외 {len(outcome.products) - 5}개" if len(outcome.products) > 5 else ""
        blocks.append(f"[검색 대상 제품 {len(outcome.products)}개: {names}{more}]")
    used = sum(len(b) for b in blocks)
    omitted = 0
    for index, hit in enumerate(outcome.hits):
        name, maker = _product_label(hit.sources, hit.source_count)
        section = SECTION_LABELS.get(hit.section_type, hit.section_type)
        similarity = max(0.0, 1.0 - hit.distance)
        header = f"[출처 | {name} | {section} | 유사도 {similarity:.3f}]"
        body, cut = cut_at_sentence(hit.content, MAX_CONTENT_CHARS)
        block = f"{header}\n{body}" + ("…(이하 생략)" if cut else "")
        if index > 0 and used + len(block) + 2 > MAX_SEARCH_RESULT_CHARS:
            omitted += 1  # 첫 문단은 항상 싣고, 상한을 넘기는 뒤쪽(유사도가 더 낮은) 문단은 뺀다
            continue
        used += len(block) + 2
        blocks.append(block)
        evidence.append(
            Evidence(
                product_name=hit.sources[0]["product_name"] if hit.sources else name,
                manufacturer=maker,
                section_type=hit.section_type,
                shared_count=max(hit.source_count, 1),
            )
        )
    if omitted:
        blocks.append(f"[참고] 길이 제한으로 관련도가 낮은 문단 {omitted}개는 생략했습니다.")
    text = "\n\n".join(blocks)
    return ToolResult(text, evidence)


def _clean_str(value: Any, limit: int, nfkc: bool = False) -> str | None:
    """공백 정리. NFKC 는 ID 처럼 ASCII 여야 하는 값에만 쓴다(제품명의 'Ⅱ', '㎎' 같은 글자를 바꾸면 못 찾는다)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("문자열이어야 합니다.")
    if nfkc:
        value = unicodedata.normalize("NFKC", value)
    value = " ".join(value.split())
    if len(value) > limit:
        raise ValueError(f"{limit}자를 넘을 수 없습니다.")
    return value or None


class DrugSearchTool:
    """search_drug_info 실행기. DB 연결 팩토리와 임베더를 주입받는다."""

    def __init__(self, settings: V2Settings, reader_factory: ReaderFactory, embedder: QueryEmbedder) -> None:
        self._settings = settings
        self._reader_factory = reader_factory
        self._embedder = embedder

    @property
    def spec(self) -> dict[str, Any]:
        return build_tool_spec(self._settings.allow_global_search)

    async def run(self, arguments: Any) -> ToolResult:
        # 1) 인자 검증 - 고칠 수 있는 오류는 모델에게 되돌려 다시 호출하게 한다.
        try:
            if not isinstance(arguments, dict):
                raise ValueError("인자는 객체여야 합니다.")
            product_name = _clean_str(arguments.get("product_name"), MAX_NAME_CHARS)
            question = _clean_str(arguments.get("question"), MAX_QUESTION_CHARS)
            section = _clean_str(arguments.get("section"), 30)
            if not question:
                raise ValueError("question 이 필요합니다.")
            if section is not None and section not in SECTION_TYPES:
                raise ValueError("section 값이 올바르지 않습니다.")
        except ValueError as exc:
            return ToolResult(f"[인자 오류] {exc}", is_error=True)

        # 2) 임베딩은 트랜잭션 밖에서(네트워크 호출 동안 DB 트랜잭션을 열어 두지 않는다).
        #    질문 원문은 로그에 남기지 않는다.
        top_k = max(1, min(self._settings.search_top_k, 20))
        section_widened = False
        try:
            vector_text = to_vector_text(await self._embedder.embed(question))
            async with self._reader_factory() as reader:
                search_args = dict(
                    product_name=product_name, top_k=top_k, max_distance=self._settings.max_distance
                )
                outcome = await retrieve(reader, self._settings, vector_text, section_type=section, **search_args)
                if section and outcome.status == "ok" and not outcome.hits:
                    # 모델이 고른 정보 유형(section)에 관련 문단이 없다 → 한 번만 모든 유형으로 넓혀 찾는다.
                    # (같은 임계값을 쓰므로 무관한 문단이 들어오지는 않는다. 임베딩은 다시 부르지 않는다.)
                    outcome = await retrieve(reader, self._settings, vector_text, section_type=None, **search_args)
                    section_widened = True
        except Exception as exc:  # noqa: BLE001 - 상세 메시지는 남기지 않는다.
            logger.error("search_drug_info 실패: %s", safe_error_name(exc))
            return ToolResult("[검색 오류] 지금은 정보를 조회할 수 없습니다.", is_error=True)

        result = format_outcome(outcome, product_name)
        if section_widened and result.evidence:
            note = (
                f"[참고] 요청한 정보 유형('{SECTION_LABELS.get(section, section)}')에서는 관련 문단이 없어 "
                "모든 정보 유형에서 찾았습니다. 아래 출처의 항목을 밝혀 답하세요."
            )
            result = ToolResult(f"{note}\n\n{result.text}", result.evidence, result.is_error, result.candidates)
        logger.info(
            "search_drug_info status=%s hits=%d filtered=%d mode=%s",
            outcome.status, len(outcome.hits), outcome.filtered, outcome.match_mode,
        )
        return result

"""도구 호출 에이전트 루프 + 외부 진입점 answer() (강의의 graph.py 에 해당).

langchain/langgraph 없이 anthropic SDK 의 tools 기능을 직접 돌린다.

    질문 → [모델 호출 → (tool_use 가 있으면) 도구 실행 → tool_result 를 붙여 다시 호출] 반복 → 최종 답변

규칙(코드로 강제)
- 한도: 도구 라운드 수 / 도구 호출 횟수 / 전체 시간 (harness.Limits)
- 허용 목록 밖의 도구 이름은 실행하지 않고 오류 결과를 돌려준다
- 근거 없음 → 모델이 뭐라고 답했든 "확인할 수 없어요" 고정 문구로 대체 (추측 답변 차단)
- 근거 있음 → 답변 끝에 면책 문구를 코드가 붙인다. sources 는 모델이 아니라 실제 검색 결과에서 만든다
- 로그에는 질문/답변 본문/도구 인자를 남기지 않는다(건강 정보). 건수와 상태만 남긴다.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.llm.v2.aws_auth import ensure_credentials
from app.llm.v2.config import V2Settings
from app.llm.v2.db import build_engine, reader_factory_for, safe_error_name
from app.llm.v2.contra_rds import RdsContraStore
from app.llm.v2.contra_store import ContraStore
from app.llm.v2.contra_tool import CONTRA_TOOL_NAME, ContraindicationTool
from app.llm.v2.embedder import QueryEmbedder
from app.llm.v2.harness import (
    Budget,
    BudgetExceededError,
    Limits,
    ToolNotAllowedError,
    assert_allowed_tool,
)
from app.llm.v2.llm_client import CreateMessage, build_create_message
from app.llm.v2.prompts import (
    BUDGET_ANSWER,
    CONTRA_PROMPT_ADDENDUM,
    CRISIS_ANSWER,
    EMERGENCY_NOTICE,
    ERROR_ANSWER,
    FORCED_FINAL_HINT,
    NO_EVIDENCE_ANSWER,
    NON_DRUG_ANSWER,
    OFF_TOPIC_MARKER,
    OUT_OF_SCOPE_ANSWER,
    SAFETY_FOOTER,
    STOP_CONSULT_ANSWER,
    SYSTEM_PROMPT,
    TIMEOUT_ANSWER,
    TRUNCATED_NOTICE,
    build_clarification_answer,
    build_user_content,
)
from app.llm.v2.names import clean_product_names, expand_with_given
from app.llm.v2.safety import is_crisis, is_emergency, is_stop_question
from app.llm.v2.textcut import drop_unfinished_tail
from app.llm.v2.tools import TOOL_NAME, DrugSearchTool, Evidence

DEFAULT_CONTRA_DB = Path(__file__).resolve().parent / "dev_data" / "contraindication.sqlite"

logger = logging.getLogger(__name__)


@dataclass
class AgentAnswer:
    answer: str
    sources: list[str] = field(default_factory=list)  # "제품명 · 섹션" (실제 검색 결과 기반)
    tools_used: list[str] = field(default_factory=list)
    rounds: int = 0
    grounded: bool = False  # 검색 근거가 있었는가
    stop_reason: str = "done"  # done|no_evidence|needs_clarification|consult|budget|timeout|error|refusal|crisis|empty
    emergency: bool = False
    # needs_clarification 일 때 사용자에게 보여 줄 제품 후보. 사용자가 고르면 사용자가 제품명을 제조사까지 적어 다시 질문하게 한다.
    candidates: list[dict[str, Any]] = field(default_factory=list)
    # --- 모델 비교/평가용 계측 (사용자 응답에는 쓰지 않는다) ---
    evidence: list[Evidence] = field(default_factory=list)
    input_tokens: int = 0  # 캐시 없이 처리된 입력 토큰(캐시 읽기·쓰기는 아래 별도)
    output_tokens: int = 0
    cache_read_tokens: int = 0  # 프롬프트 캐시에서 읽은 입력 토큰(저렴한 단가)
    cache_write_tokens: int = 0  # 프롬프트 캐시에 새로 쓴 입력 토큰(첫 호출, 단가 1.25배)
    elapsed_seconds: float = 0.0
    truncated: bool = False  # 답변이 max_tokens 에 걸려 중간에 끊겨 정리했는가
    # 도구 호출별 {arguments(제품명·섹션·질문), result_head(결과 첫머리)}. 원인 분석용이며 로그에는 남기지 않는다.
    tool_trace: list[dict[str, Any]] = field(default_factory=list)


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _usage(response: Any) -> tuple[int, int, int, int]:
    """(캐시 없이 처리된 입력, 출력, 캐시 읽기, 캐시 쓰기) 토큰. Anthropic 의 input_tokens 는 캐시 읽기·쓰기를 뺀 값이다."""
    usage = _get(response, "usage")
    if usage is None:
        return 0, 0, 0, 0
    return (
        int(_get(usage, "input_tokens") or 0),
        int(_get(usage, "output_tokens") or 0),
        int(_get(usage, "cache_read_input_tokens") or 0),
        int(_get(usage, "cache_creation_input_tokens") or 0),
    )


def _block_kinds(response: Any) -> str:
    """응답 content 블록 종류별 개수(예: 'text=1,tool_use=2'). 보이지 않는 블록(thinking 등)도 센다. 내용은 남기지 않는다."""
    counts: dict[str, int] = {}
    for block in _get(response, "content") or []:
        kind = str(_get(block, "type") or "?")
        counts[kind] = counts.get(kind, 0) + 1
    return ",".join(f"{k}={v}" for k, v in counts.items()) or "-"


def _normalize_blocks(response: Any) -> list[dict[str, Any]]:
    """SDK 응답 블록(객체) → 다음 요청에 되돌려 보낼 수 있는 dict. text/tool_use 만 사용한다."""
    blocks: list[dict[str, Any]] = []
    for block in _get(response, "content") or []:
        kind = _get(block, "type")
        if kind == "text":
            blocks.append({"type": "text", "text": _get(block, "text") or ""})
        elif kind == "tool_use":
            blocks.append(
                {"type": "tool_use", "id": _get(block, "id"), "name": _get(block, "name"), "input": _get(block, "input") or {}}
            )
    return blocks


def _expand_given_names(tool_name: str, arguments: Any, given: list[str]) -> Any:
    """모델이 도구에 넣은 제품명을 호출자가 넘긴 제품명(OCR 등)의 더 긴 표기로 보강한다(제조사까지 적힌 표기 등)."""
    if not given or not isinstance(arguments, dict):
        return arguments
    if tool_name == TOOL_NAME and isinstance(arguments.get("product_name"), str):
        return {**arguments, "product_name": expand_with_given(arguments["product_name"], given)}
    if tool_name == CONTRA_TOOL_NAME and isinstance(arguments.get("products"), list):
        return {**arguments, "products": [expand_with_given(p, given) if isinstance(p, str) else p for p in arguments["products"]]}
    return arguments


class DrugInfoAgent:
    def __init__(
        self,
        create_message: CreateMessage,
        tool: DrugSearchTool,
        limits: Limits,
        engine: Any = None,
        contra_tool: ContraindicationTool | None = None,
        prompt_cache: bool = False,
    ) -> None:
        self._create = create_message
        self._prompt_cache = prompt_cache
        self._tool = tool
        self._limits = limits
        self._engine = engine
        # 이름 → 실행기. 병용금기 도구는 인덱스 파일이 있을 때만 켜지고, 켜졌을 때만 프롬프트가 언급한다.
        self._tools: dict[str, Any] = {TOOL_NAME: tool}
        self._system = SYSTEM_PROMPT
        if contra_tool is not None:
            self._tools[CONTRA_TOOL_NAME] = contra_tool
            self._system = SYSTEM_PROMPT + CONTRA_PROMPT_ADDENDUM

    @property
    def tool_names(self) -> list[str]:
        """켜져 있는 도구 이름(병용금기 도구는 인덱스 파일이 있을 때만 포함)."""
        return list(self._tools)

    async def aclose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    async def _call_model(self, messages: list[dict[str, Any]], budget: Budget) -> Any:
        tools = [t.spec for t in self._tools.values()]
        if self._prompt_cache:
            # 캐시 구간은 tools → system 순서의 앞부분. system 블록 끝에 표시하면 도구 정의와 시스템 프롬프트가 함께 캐시된다.
            system: Any = [{"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}}]
        else:
            system = self._system
        try:
            return await asyncio.wait_for(
                self._create(system=system, tools=tools, messages=list(messages)), timeout=budget.remaining_seconds()
            )
        except Exception as exc:  # noqa: BLE001
            if self._prompt_cache and "cache_control" in str(exc).lower():  # 이 엔드포인트·모델이 캐시 표시를 받지 않는다 → 끄고 한 번 다시
                logger.warning("프롬프트 캐시를 지원하지 않아 끕니다: %s", safe_error_name(exc))
                self._prompt_cache = False
                return await asyncio.wait_for(
                    self._create(system=self._system, tools=tools, messages=list(messages)), timeout=budget.remaining_seconds()
                )
            raise

    async def _run_tool(
        self,
        block: dict[str, Any],
        budget: Budget,
        evidence: list[Evidence],
        tools_used: list[str],
        pending: dict[str, list[dict[str, Any]]],
        trace: list[dict[str, Any]] | None = None,
        given: list[str] | None = None,
    ) -> dict[str, Any]:
        def result(text: str, is_error: bool = False) -> dict[str, Any]:
            item = {"type": "tool_result", "tool_use_id": block["id"], "content": text}
            if is_error:
                item["is_error"] = True
            return item

        name = str(block.get("name") or "")
        try:
            assert_allowed_tool(name)
        except ToolNotAllowedError:
            logger.warning("허용되지 않은 도구 요청 차단")
            return result("허용되지 않은 도구입니다. 제공된 도구만 사용할 수 있습니다.", True)
        runner = self._tools.get(name)
        if runner is None:  # 허용 목록에는 있지만 이 에이전트에서는 꺼져 있는 도구
            return result("지금은 사용할 수 없는 도구입니다.", True)
        if not budget.can_call_tool():
            return result("도구 호출 횟수 한도를 넘었습니다. 지금까지의 결과로 답하세요.", True)

        budget.check_time()
        budget.consume_call()
        arguments = block.get("input")
        arguments = _expand_given_names(name, arguments, given or [])
        outcome = await asyncio.wait_for(runner.run(arguments), timeout=budget.remaining_seconds())
        tools_used.append(name)
        if trace is not None:
            shown = arguments if isinstance(arguments, dict) else {}
            trace.append({
                "arguments": {k: shown.get(k) for k in ("product_name", "section", "question", "products") if k in shown},
                "result_head": outcome.text[:80],
            })
        evidence.extend(outcome.evidence)
        # 되묻기(제품 후보)는 풀릴 때까지 '해결 안 됨'으로 들고 간다. 같은 이름으로 다시 찾아 근거가 나오면 풀린 것이다.
        shown_args = arguments if isinstance(arguments, dict) else {}
        pending_key = name if name != TOOL_NAME else " ".join(str(shown_args.get("product_name") or "").split()).casefold()
        if outcome.candidates:
            pending[pending_key] = list(outcome.candidates)
        elif outcome.evidence:
            pending.pop(pending_key, None)
        return result(outcome.text, outcome.is_error)

    async def run(
        self,
        question: str,
        profile_context: str | None = None,
        products: list[str] | None = None,
    ) -> AgentAnswer:
        started = time.monotonic()
        question = (question or "").strip()[: self._limits.max_question_chars]
        if not question:
            return AgentAnswer("질문을 입력해 주세요.", stop_reason="empty")
        if is_crisis(question):
            return AgentAnswer(CRISIS_ANSWER, stop_reason="crisis", emergency=True)

        emergency = is_emergency(question)
        if not emergency and is_stop_question(question):  # 끊어도 되는지는 근거 검색 없이 상담 안내로 답한다(응급이면 아래 일반 경로의 119 안내가 우선)
            return AgentAnswer(STOP_CONSULT_ANSWER, stop_reason="consult")
        budget = Budget(self._limits)
        given = clean_product_names(products)
        messages: list[dict[str, Any]] = [{"role": "user", "content": build_user_content(question, profile_context, given)}]
        evidence: list[Evidence] = []
        pending: dict[str, list[dict[str, Any]]] = {}
        tools_used: list[str] = []
        trace: list[dict[str, Any]] = []
        final_text = ""
        truncated = False
        stop = "done"
        tokens_in = tokens_out = cache_read = cache_write = 0

        try:
            while True:
                budget.check_time()
                forced_final = budget.rounds_left <= 0  # 도구 라운드를 다 썼다 → 이번 호출은 최종 답변이어야 한다
                response = await self._call_model(messages, budget)
                used_in, used_out, used_read, used_write = _usage(response)
                tokens_in, tokens_out = tokens_in + used_in, tokens_out + used_out
                cache_read, cache_write = cache_read + used_read, cache_write + used_write

                model_stop = _get(response, "stop_reason")
                logger.info(
                    "model_call round=%d model_stop=%s blocks=%s input=%d output=%d cache_read=%d cache_write=%d",
                    budget.rounds, model_stop, _block_kinds(response), used_in, used_out, used_read, used_write,
                )
                if model_stop == "refusal":
                    stop = "refusal"
                    break
                blocks = _normalize_blocks(response)
                tool_uses = [b for b in blocks if b["type"] == "tool_use"]
                if model_stop == "max_tokens" and tool_uses:
                    logger.error("도구 요청이 max_tokens 에서 끊겼습니다(입력이 불완전할 수 있음)")
                    stop = "error"
                    break
                if not tool_uses:
                    final_text = "".join(b["text"] for b in blocks if b["type"] == "text")
                    if model_stop == "max_tokens":  # 답이 길어 중간에 끊겼다 → 미완성 문장을 지우고 알린다
                        truncated = True
                        final_text = f"{drop_unfinished_tail(final_text)}\n\n{TRUNCATED_NOTICE}"
                    break
                if forced_final:
                    stop = "budget"  # 한도를 다 썼는데도 도구를 또 부르려 한다
                    break

                budget.consume_round()
                messages.append({"role": "assistant", "content": blocks})
                results = [await self._run_tool(b, budget, evidence, tools_used, pending, trace, given) for b in tool_uses]
                if budget.rounds_left <= 0:
                    results.append({"type": "text", "text": FORCED_FINAL_HINT})
                messages.append({"role": "user", "content": results})
        except (asyncio.TimeoutError, BudgetExceededError):
            stop = "timeout"
        except Exception as exc:  # noqa: BLE001 - 상세 메시지는 남기지 않는다.
            logger.error("agent 실패: %s", safe_error_name(exc))
            stop = "error"

        candidates = next(iter(pending.values()), [])  # 먼저 생긴 해결 안 된 되묻기
        answer = self._assemble(stop, final_text, evidence, tools_used, budget.rounds, emergency, candidates)
        answer.evidence = list(evidence)
        answer.tool_trace = trace
        answer.input_tokens, answer.output_tokens = tokens_in, tokens_out
        answer.cache_read_tokens, answer.cache_write_tokens = cache_read, cache_write
        answer.truncated = truncated and answer.stop_reason == "done"
        answer.elapsed_seconds = time.monotonic() - started
        logger.info(
            "agent stop=%s truncated=%s rounds=%d calls=%d evidence=%d elapsed=%.1fs",
            answer.stop_reason, answer.truncated, budget.rounds, budget.calls, len(evidence), time.monotonic() - started,
        )
        return answer

    @staticmethod
    def _assemble(
        stop: str,
        final_text: str,
        evidence: list[Evidence],
        tools_used: list[str],
        rounds: int,
        emergency: bool,
        candidates: list[dict[str, Any]] | None = None,
    ) -> AgentAnswer:
        candidates = candidates or []
        sources = list(dict.fromkeys(e.label for e in evidence))
        grounded = False
        if stop == "timeout":
            text = TIMEOUT_ANSWER
        elif stop == "budget":
            text = BUDGET_ANSWER
        elif stop in ("error", "refusal"):
            text = ERROR_ANSWER
        elif candidates:
            # 제품 후보가 여럿이라 풀리지 않았다 → 다른 제품의 근거가 있어도 되묻기를 우선한다.
            # 모델 문장 대신 코드가 후보 목록으로 만든다(모델 지식이 섞이지 않게).
            food_combination = CONTRA_TOOL_NAME in tools_used and any(
                str(c.get("product_key", "")).startswith("health_food:") for c in candidates
            )
            text, stop = build_clarification_answer(candidates, food_combination=food_combination), "needs_clarification"
        elif not evidence:
            # 근거가 하나도 없으면 모델의 문장은 쓰지 않는다. 도구를 한 번도 못 쓴 경우(약 이름 없음·범위 밖 질문)는 할 수 있는 일을 안내한다.
            if tools_used:
                text = NO_EVIDENCE_ANSWER
            elif final_text.strip().startswith(OFF_TOPIC_MARKER):  # 모델이 약과 무관한 질문이라고 표시했다
                text = NON_DRUG_ANSWER
            else:
                text = OUT_OF_SCOPE_ANSWER
            stop = "no_evidence"
        elif not final_text.strip():
            text, stop = ERROR_ANSWER, "error"
        else:
            text, grounded = f"{final_text.strip()}\n\n{SAFETY_FOOTER}", True
        if emergency and stop in ("no_evidence", "needs_clarification"):
            # 근거 없는 답이나 제품 되묻기를 응급 안내 뒤에 이어 붙이지 않는다 — 119 안내만. 되묻기는 후보도 내보내지 않는다.
            text, stop = EMERGENCY_NOTICE, "no_evidence"
        elif emergency:
            text = f"{EMERGENCY_NOTICE}\n\n{text}"
        return AgentAnswer(
            answer=text,
            sources=sources if grounded else [],
            tools_used=tools_used,
            rounds=rounds,
            grounded=grounded,
            stop_reason=stop,
            emergency=emergency,
            candidates=candidates if stop == "needs_clarification" else [],
        )


# --------------------------------------------------------------------------- 외부 진입점

_agent: DrugInfoAgent | None = None
_agent_lock = asyncio.Lock()


def build_agent(settings: V2Settings | None = None) -> DrugInfoAgent:
    settings = settings or V2Settings.from_env()
    ensure_credentials(settings)  # EC2 에서는 인스턴스 역할 자격증명이 아니면 시작을 막는다(로컬은 통과)
    engine = build_engine(settings)
    open_reader = reader_factory_for(engine)
    tool = DrugSearchTool(settings, open_reader, QueryEmbedder(settings))
    contra_tool = _build_contra_tool(settings, open_reader)
    return DrugInfoAgent(build_create_message(settings), tool, Limits.from_settings(settings), engine, contra_tool, settings.prompt_cache)


def _build_contra_tool(settings: V2Settings, open_reader: Any) -> ContraindicationTool | None:
    """병용금기 도구를 켠다. 출처는 LLM_V2_CONTRA_SOURCE 로 고르고, 기본(auto)은 아래 순서다.

    1) LLM_V2_CONTRA_DB 를 지정했으면 그 SQLite(없으면 오류: 설정 실수)  2) dev_data/contraindication.sqlite 가 있으면 그 파일
    3) 둘 다 없으면 RDS 의 gold.drug_contraindication (EC2 처럼 파일 없이 DB 만 쓰는 환경).
    sqlite 를 명시했는데 파일이 없으면 오류, off 면 끈다.
    """
    source = settings.contra_source
    if source == "off":
        logger.info("LLM_V2_CONTRA_SOURCE=off 라 check_contraindication 을 끕니다.")
        return None
    if source == "rds":
        return ContraindicationTool(settings, open_reader, RdsContraStore())
    if source == "sqlite":
        return ContraindicationTool(settings, open_reader, ContraStore(settings.contra_db_path or DEFAULT_CONTRA_DB))
    if settings.contra_db_path:
        return ContraindicationTool(settings, open_reader, ContraStore(settings.contra_db_path))  # 없으면 ContraStoreError
    if DEFAULT_CONTRA_DB.is_file():
        return ContraindicationTool(settings, open_reader, ContraStore(DEFAULT_CONTRA_DB))
    return ContraindicationTool(settings, open_reader, RdsContraStore())


async def _get_agent() -> DrugInfoAgent:
    global _agent
    async with _agent_lock:
        if _agent is None:
            _agent = build_agent()
        return _agent


async def answer(
    question: str,
    profile_context: str | None = None,
    products: list[str] | None = None,
) -> AgentAnswer:
    """채팅 라우터가 부를 단일 진입점. 예외를 밖으로 던지지 않고 항상 AgentAnswer 를 돌려준다.

    사용 예(나중에 라우터에서 한 줄):  result = await llm_v2.agent.answer(question, profile_context)
    stop_reason 이 "needs_clarification" 이면 result.answer(겹치는 제품 목록과 다시 입력 안내)를 사용자에게 보여 주고,
    사용자가 제품명을 제조사까지 적어 다시 질문하면 그 질문으로 다시 호출한다.
    OCR 등으로 제품명 목록을 이미 알고 있으면 products=[...](최대 8개)로 넘긴다. 약 이름을 다시 묻지 않고 그 목록으로 조회한다.
    """
    try:
        agent = await _get_agent()
        return await agent.run(question, profile_context, products)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 설정 누락 등. 상세 메시지(비밀 가능성)는 남기지 않는다.
        logger.error("answer 실패: %s", safe_error_name(exc))
        return AgentAnswer(ERROR_ANSWER, stop_reason="error")


async def aclose() -> None:
    """앱 종료 시 DB 엔진 정리(선택)."""
    global _agent
    if _agent is not None:
        await _agent.aclose()
        _agent = None

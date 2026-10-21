"""HTTP API 테스트: 가짜 에이전트로 요청 검증·인증·상태 코드·동시 요청 제한을 확인한다(Bedrock/DB 호출 없음)."""
import asyncio
import logging

from fastapi.testclient import TestClient

from app.llm.v2 import api as api_module
from app.llm.v2.agent import AgentAnswer
from app.llm.v2.api import BUSY_MESSAGE, create_app
from app.llm.v2.prompts import ERROR_ANSWER, TIMEOUT_ANSWER
from app.llm.v2.tests.helpers import make_settings

GOOD = AgentAnswer(
    "타이레놀은 해열진통제예요.\n\n※ 안내",
    sources=["타이레놀정500밀리그램 · 효능·효과"],
    tools_used=["search_drug_info"],
    rounds=1,
    grounded=True,
    input_tokens=1200,
    output_tokens=80,
    elapsed_seconds=1.234,
)


class FakeAgent:
    def __init__(self, result=GOOD, delay=0.0, error=None):
        self.result, self.delay, self.error = result, delay, error
        self.calls, self.closed, self.active, self.peak = [], False, 0, 0

    tool_names = ["search_drug_info", "check_contraindication"]

    async def run(self, question, profile_context=None, product_key=None):
        self.calls.append((question, profile_context, product_key))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error:
                raise self.error
            return self.result
        finally:
            self.active -= 1

    async def aclose(self):
        self.closed = True


def client_for(agent=None, **settings):
    agent = agent or FakeAgent()
    return TestClient(create_app(make_settings(**settings), agent)), agent


def test_ask_returns_structured_answer():
    client, agent = client_for()
    with client:
        response = client.post("/llm/v2/ask", json={"question": "  타이레놀 효능이 뭐예요?  "})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done" and body["grounded"] is True and body["emergency"] is False
    assert body["answer"].startswith("타이레놀은")
    assert body["sources"] == ["타이레놀정500밀리그램 · 효능·효과"]
    assert body["tools_used"] == ["search_drug_info"] and body["rounds"] == 1
    assert body["usage"] == {"input_tokens": 1200, "output_tokens": 80}
    assert body["latency_ms"] == 1234 and body["model_id"] == "test-model"
    assert "tool_trace" not in body and "evidence" not in body  # 내부 계측은 노출하지 않는다
    assert agent.calls == [("타이레놀 효능이 뭐예요?", None, None)]  # 앞뒤 공백 제거


def test_ask_passes_product_key_and_profile():
    client, agent = client_for()
    with client:
        response = client.post(
            "/llm/v2/ask", json={"question": "보관은?", "product_key": "drug:195700010", "profile_context": "30대 임산부"}
        )
    assert response.status_code == 200
    assert agent.calls == [("보관은?", "30대 임산부", "drug:195700010")]


def test_ask_validation_errors():
    client, agent = client_for()
    with client:
        post = lambda payload: client.post("/llm/v2/ask", json=payload).status_code  # noqa: E731
        assert post({}) == 422
        assert post({"question": "   "}) == 422  # 공백만
        assert post({"question": "x" * 1001}) == 422  # 스키마 상한
        assert post({"question": "a", "product_key": "drug:1; DROP TABLE x"}) == 422  # 형식 위반
        assert post({"question": "a", "product_key": "unknown:123"}) == 422
        assert post({"question": "a", "extra": 1}) == 422  # 알 수 없는 필드
        assert post({"question": "a", "profile_context": "p" * 1001}) == 422
    assert agent.calls == []  # 검증 실패는 에이전트에 도달하지 않는다


def test_ask_rejects_question_longer_than_setting():
    client, agent = client_for(max_question_chars=10)
    with client:
        response = client.post("/llm/v2/ask", json={"question": "가" * 11})
    assert response.status_code == 422 and "10자" in response.json()["detail"]
    assert agent.calls == []


def test_policy_outcomes_are_200_with_status():
    clarify = AgentAnswer(
        "어느 제품인가요?", stop_reason="needs_clarification",
        candidates=[{"product_key": "drug:1", "product_name": "라식스주사", "manufacturer": "A사"},
                    {"product_key": "drug:2", "product_name": "라식스정", "manufacturer": None}],
    )
    for result, status in ((clarify, "needs_clarification"), (AgentAnswer("근거 없음", stop_reason="no_evidence"), "no_evidence"),
                           (AgentAnswer("위기 안내", stop_reason="crisis", emergency=True), "crisis")):
        client, _ = client_for(FakeAgent(result))
        with client:
            response = client.post("/llm/v2/ask", json={"question": "질문"})
        assert response.status_code == 200 and response.json()["status"] == status
    body = response.json()
    assert body["emergency"] is True and body["grounded"] is False
    client, _ = client_for(FakeAgent(clarify))
    with client:
        candidates = client.post("/llm/v2/ask", json={"question": "라식스"}).json()["candidates"]
    assert candidates == [
        {"product_key": "drug:1", "product_name": "라식스주사", "manufacturer": "A사"},
        {"product_key": "drug:2", "product_name": "라식스정", "manufacturer": None},
    ]


def test_service_failures_are_http_errors_without_internal_details():
    for result, code, message in (
        (AgentAnswer(ERROR_ANSWER, stop_reason="error"), 503, ERROR_ANSWER),
        (AgentAnswer(TIMEOUT_ANSWER, stop_reason="timeout"), 504, TIMEOUT_ANSWER),
    ):
        client, _ = client_for(FakeAgent(result))
        with client:
            response = client.post("/llm/v2/ask", json={"question": "질문"})
        assert response.status_code == code and response.json() == {"detail": message}


def test_unexpected_exception_hides_details_and_logs_only_the_class(caplog=None):
    secret_error = RuntimeError("password=hunter2 question=내 질문")
    client, _ = client_for(FakeAgent(error=secret_error))
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    api_module.logger.addHandler(handler)
    try:
        with client:
            response = client.post("/llm/v2/ask", json={"question": "내 질문"})
    finally:
        api_module.logger.removeHandler(handler)
    assert response.status_code == 503 and response.json() == {"detail": ERROR_ANSWER}
    assert "hunter2" not in response.text and all("hunter2" not in m and "내 질문" not in m for m in records)
    assert any("RuntimeError" in m for m in records)


def test_api_key_is_required_when_configured():
    client, agent = client_for(api_key="s3cret-key")
    with client:
        ask = lambda **kw: client.post("/llm/v2/ask", json={"question": "질문"}, **kw)  # noqa: E731
        assert ask().status_code == 401
        assert ask(headers={"X-API-Key": "wrong"}).status_code == 401
        assert ask(headers={"X-API-Key": ""}).status_code == 401
        assert ask(headers={"X-API-Key": "s3cret-key"}).status_code == 200
        assert client.get("/llm/v2/models").status_code == 401
        assert client.get("/llm/v2/models", headers={"X-API-Key": "s3cret-key"}).status_code == 200
        assert client.get("/llm/v2/health").status_code == 200  # 생존 확인은 인증 없이
    assert len(agent.calls) == 1  # 인증 실패 요청은 에이전트에 도달하지 않는다


def test_non_ascii_api_key_header_is_rejected_not_crashing():
    client, agent = client_for(api_key="s3cret-key")
    with client:
        response = client.post("/llm/v2/ask", json={"question": "q"}, headers={"X-API-Key": "키-값".encode()})
    assert response.status_code == 401 and agent.calls == []


def test_open_mode_without_api_key_warns():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture()
    api_module.logger.addHandler(handler)
    try:
        client, _ = client_for()
        with client:
            assert client.post("/llm/v2/ask", json={"question": "질문"}).status_code == 200
    finally:
        api_module.logger.removeHandler(handler)
    assert any("LLM_V2_API_KEY" in m for m in records)


def test_models_and_health():
    client, _ = client_for(default_model="sonnet", llm_model_id=None)
    with client:
        assert client.get("/llm/v2/health").json() == {"status": "ok"}
        body = client.get("/llm/v2/models").json()
    assert body["default"] == "sonnet" and body["model_id"] == "us.anthropic.claude-sonnet-5-5"
    assert body["tools"] == ["search_drug_info", "check_contraindication"] and body["max_distance"] == 0.80


def test_concurrency_limit_queues_then_rejects_with_503():
    agent = FakeAgent(delay=0.4)
    client, _ = client_for(agent, api_max_concurrency=1, api_queue_seconds=0.05)

    async def scenario():
        import httpx

        transport = httpx.ASGITransport(app=client.app)
        async with client.app.router.lifespan_context(client.app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
                first = asyncio.create_task(http.post("/llm/v2/ask", json={"question": "하나"}))
                await asyncio.sleep(0.1)  # 첫 요청이 자리를 잡은 뒤
                second = await http.post("/llm/v2/ask", json={"question": "둘"})
                return await first, second

    first, second = asyncio.run(scenario())
    assert first.status_code == 200
    assert second.status_code == 503 and second.json() == {"detail": BUSY_MESSAGE}
    assert second.headers.get("retry-after") == "1"
    assert agent.peak == 1 and len(agent.calls) == 1  # 두 번째는 에이전트까지 가지 않았다


def test_slot_is_released_after_each_request():
    agent = FakeAgent()
    client, _ = client_for(agent, api_max_concurrency=1, api_queue_seconds=0.05)
    with client:
        for _ in range(3):
            assert client.post("/llm/v2/ask", json={"question": "질문"}).status_code == 200
    agent2 = FakeAgent(error=ValueError("boom"))
    client2, _ = client_for(agent2, api_max_concurrency=1, api_queue_seconds=0.05)
    with client2:
        assert client2.post("/llm/v2/ask", json={"question": "a"}).status_code == 503
        agent2.error = None
        assert client2.post("/llm/v2/ask", json={"question": "b"}).status_code == 200  # 오류 뒤에도 자리가 반환됨


def test_lifespan_closes_agent():
    client, agent = client_for()
    with client:
        assert agent.closed is False
    assert agent.closed is True


def test_module_app_builds_agent_lazily_from_env():
    # import 만으로는 환경변수·DB·AWS 에 접근하지 않는다(앱이 시작될 때만 에이전트를 만든다).
    assert api_module.app.title == "약온 LLM v2"
    assert not hasattr(api_module.app.state, "llm_agent")

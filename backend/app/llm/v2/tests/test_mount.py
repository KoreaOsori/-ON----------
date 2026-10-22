"""백엔드 앱에 v2 를 mount 하는 구성 테스트: 경로·문서·인증·실패 시 격리·종료 정리를 확인한다(가짜 에이전트, Bedrock/DB 없음)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.v2.api import create_app, mounted_lifespan
from app.llm.v2.tests.helpers import make_settings
from app.llm.v2.tests.test_api import FakeAgent


def parent_for(child):
    @asynccontextmanager
    async def lifespan(app):
        async with mounted_lifespan(child):
            yield

    parent = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None)  # 운영 설정처럼 부모 문서는 끈다
    parent.mount("/api/llm/v2", child)

    @parent.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    return parent


def child_with(agent=None, **settings):
    agent = agent or FakeAgent()
    return create_app(make_settings(**settings), agent, route_prefix="", require_api_key=True), agent


def test_mounted_paths_docs_schema_and_auth():
    child, agent = child_with(api_key="s3cret-v2-key")
    with TestClient(parent_for(child)) as client:
        docs = client.get("/api/llm/v2/docs")
        assert docs.status_code == 200 and "/api/llm/v2/openapi.json" in docs.text
        assert "persistAuthorization" in docs.text  # Authorize 의 키를 새로고침해도 유지(브라우저 저장)
        schema = client.get("/api/llm/v2/openapi.json").json()
        assert schema["servers"] == [{"url": "/api/llm/v2"}]
        assert {"/ask", "/models", "/health"} <= set(schema["paths"])
        assert client.get("/api/llm/v2/health").json() == {"status": "ok"}
        assert client.post("/api/llm/v2/ask", json={"question": "타이레놀 효능?"}).status_code == 401
        ok = client.post("/api/llm/v2/ask", json={"question": "타이레놀 효능?"}, headers={"X-API-Key": "s3cret-v2-key"})
        assert ok.status_code == 200 and ok.json()["status"] == "done"
        assert client.get("/api/llm/v2/models", headers={"X-API-Key": "s3cret-v2-key"}).status_code == 200
        assert client.get("/api/v1/ping").json() == {"ok": True}  # 기존 백엔드 경로는 그대로
        assert client.get("/docs").status_code == 404  # 부모 문서는 꺼져 있다
    assert agent.closed  # 부모가 끝나면 v2 도 정리된다


def test_standalone_paths_keep_llm_v2_prefix():
    client = TestClient(create_app(make_settings(), FakeAgent()))
    with client:
        assert client.get("/llm/v2/health").json() == {"status": "ok"}
        assert client.post("/llm/v2/ask", json={"question": "q"}).status_code == 200
        assert client.post("/ask", json={"question": "q"}).status_code == 404


def test_public_mount_without_api_key_is_refused_but_backend_survives():
    child, agent = child_with()  # api_key 없음
    logs = []

    class Capture(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())

    handler = Capture()
    logging.getLogger("app.llm.v2.api").addHandler(handler)
    try:
        with TestClient(parent_for(child)) as client:
            assert client.get("/api/v1/ping").json() == {"ok": True}  # 백엔드는 뜬다
            assert client.get("/api/llm/v2/health").status_code == 503
            blocked = client.post("/api/llm/v2/ask", json={"question": "q"}, headers={"X-API-Key": "anything"})
            assert blocked.status_code == 503
    finally:
        logging.getLogger("app.llm.v2.api").removeHandler(handler)
    assert agent.calls == []  # 모델은 호출되지 않았다
    assert any("LLM_V2_API_KEY" in m for m in logs)  # 운영자가 원인을 알 수 있다


def test_v2_startup_failure_does_not_take_down_backend():
    class Boom(Exception):
        pass

    def broken_agent(*args, **kwargs):
        raise Boom("DB 비밀번호가 들어 있을 수 있는 메시지")

    child = create_app(make_settings(api_key="k"), None, route_prefix="", require_api_key=True)
    import app.llm.v2.api as api_module

    original = api_module.build_agent
    api_module.build_agent = broken_agent
    logs = []

    class Capture(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())

    handler = Capture()
    logging.getLogger("app.llm.v2.api").addHandler(handler)
    try:
        with TestClient(parent_for(child)) as client:
            assert client.get("/api/v1/ping").json() == {"ok": True}
            assert client.post("/api/llm/v2/ask", json={"question": "q"}, headers={"X-API-Key": "k"}).status_code == 503
    finally:
        api_module.build_agent = original
        logging.getLogger("app.llm.v2.api").removeHandler(handler)
    joined = " ".join(logs)
    assert "Boom" in joined and "비밀번호" not in joined  # 클래스 이름만, 메시지는 남기지 않는다

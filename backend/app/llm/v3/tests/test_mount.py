"""백엔드 앱에 v2 를 mount 하는 구성 테스트: 경로·문서·실패 시 격리·종료 정리를 확인한다(가짜 에이전트, Bedrock/DB 없음)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.v3.api import create_app, mounted_lifespan
from app.llm.v3.tests.helpers import make_settings
from app.llm.v3.tests.test_api import FakeAgent


def parent_for(child):
    @asynccontextmanager
    async def lifespan(app):
        async with mounted_lifespan(child):
            yield

    parent = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None)  # 운영 설정처럼 부모 문서는 끈다
    parent.mount("/api/llm/v3", child)

    @parent.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    return parent


def child_with(agent=None, **settings):
    agent = agent or FakeAgent()
    return create_app(make_settings(**settings), agent, route_prefix=""), agent


def test_mounted_paths_docs_schema_without_auth():
    child, agent = child_with()
    with TestClient(parent_for(child)) as client:
        docs = client.get("/api/llm/v3/docs")
        assert docs.status_code == 200 and "/api/llm/v3/openapi.json" in docs.text
        schema = client.get("/api/llm/v3/openapi.json").json()
        assert schema["servers"] == [{"url": "/api/llm/v3"}]
        assert {"/ask", "/models", "/health"} <= set(schema["paths"])
        assert "securitySchemes" not in schema.get("components", {})  # Swagger 에 Authorize 버튼이 없다
        assert client.get("/api/llm/v3/health").json() == {"status": "ok"}
        ok = client.post("/api/llm/v3/ask", json={"question": "타이레놀 효능?"})  # X-API-Key 없이
        assert ok.status_code == 200 and ok.json()["status"] == "done"
        assert client.get("/api/llm/v3/models").status_code == 200
        assert client.get("/api/v1/ping").json() == {"ok": True}  # 기존 백엔드 경로는 그대로
        assert client.get("/docs").status_code == 404  # 부모 문서는 꺼져 있다
    assert agent.closed  # 부모가 끝나면 v3 도 정리된다


def test_standalone_paths_keep_llm_v3_prefix():
    client = TestClient(create_app(make_settings(), FakeAgent()))
    with client:
        assert client.get("/llm/v3/health").json() == {"status": "ok"}
        assert client.post("/llm/v3/ask", json={"question": "q"}).status_code == 200
        assert client.post("/ask", json={"question": "q"}).status_code == 404


def test_v2_startup_failure_does_not_take_down_backend():
    class Boom(Exception):
        pass

    def broken_agent(*args, **kwargs):
        raise Boom("DB 비밀번호가 들어 있을 수 있는 메시지")

    child = create_app(make_settings(), None, route_prefix="")
    import app.llm.v3.api as api_module

    original = api_module.build_agent
    api_module.build_agent = broken_agent
    logs = []

    class Capture(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())

    handler = Capture()
    logging.getLogger("app.llm.v3.api").addHandler(handler)
    try:
        with TestClient(parent_for(child)) as client:
            assert client.get("/api/v1/ping").json() == {"ok": True}
            assert client.post("/api/llm/v3/ask", json={"question": "q"}).status_code == 503
    finally:
        api_module.build_agent = original
        logging.getLogger("app.llm.v3.api").removeHandler(handler)
    joined = " ".join(logs)
    assert "Boom" in joined and "비밀번호" not in joined  # 클래스 이름만, 메시지는 남기지 않는다

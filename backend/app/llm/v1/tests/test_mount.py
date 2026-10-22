import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.v1.api import create_app, lifespan
from app.llm.v1.config import Settings


class MountedAppTests(unittest.TestCase):
    def test_public_docs_schema_auth_and_shutdown(self):
        child = create_app()

        @asynccontextmanager
        async def parent_lifespan(parent):
            async with lifespan(child):
                yield

        parent = FastAPI(lifespan=parent_lifespan, docs_url=None, openapi_url=None)
        parent.mount("/api/llm/v1", child)
        engine = MagicMock()
        engine.dispose = AsyncMock()
        with patch("app.llm.v1.api.create_database_engine", return_value=engine), patch(
            "app.llm.v1.api.Settings", return_value=Settings(_env_file=None, api_key="test-key")
        ):
            with TestClient(parent) as client:
                docs = client.get("/api/llm/v1/docs")
                self.assertEqual(docs.status_code, 200)
                self.assertIn("/api/llm/v1/openapi.json", docs.text)
                schema = client.get("/api/llm/v1/openapi.json").json()
                self.assertEqual(schema["servers"], [{"url": "/api/llm/v1"}])
                self.assertEqual(set(schema["paths"]), {"/ask", "/models"})
                self.assertEqual(client.get("/api/llm/v1/models").status_code, 401)
                result = client.get("/api/llm/v1/models", headers={"X-API-Key": "test-key"})
                self.assertEqual(result.status_code, 200)
                self.assertIn("haiku", result.json()["models"])
                self.assertEqual(client.post("/api/llm/v1/ask", json={},
                    headers={"X-API-Key": "test-key"}).status_code, 422)
                self.assertFalse(hasattr(parent.state, "llm_engine"))
            engine.dispose.assert_awaited_once()

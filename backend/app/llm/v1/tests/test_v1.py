import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.llm.v1.api import app
from app.llm.v1.bedrock import Bedrock
from app.llm.v1.config import Settings
from app.llm.v1.interactions import compare
from app.llm.v1.schemas import AskRequest, SafetyBundle
from app.llm.v1.service import Service


def product(key="drug:1", kind="drug"):
    return {"product_key": key, "product_name": key, "product_type": kind, "manufacturer": "test"}


def rule(left=None, right=None, conditions=""):
    return {"rule_id": "R1", "left_codes": left or ["A"], "right_codes": right or ["B"],
            "content": "TEST ONLY", "conditions": conditions, "source": "fixture"}


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.products = [product(), product("drug:2")]
        self.ingredients = {"drug:1": {"codes": ["A"], "complete": True},
                            "drug:2": {"codes": ["B"], "complete": True}}

    def check(self, rules, complete=True):
        return compare(self.products, self.ingredients, rules, complete)[0]

    def test_reverse_direction(self):
        self.assertEqual(self.check([rule(["B"], ["A"])])["status"], "contraindicated")

    def test_combination_requires_all_codes(self):
        self.assertEqual(self.check([rule(["A", "C"])])["status"], "not_found")

    def test_conditions_are_preserved(self):
        result = self.check([rule(conditions="specific route only")])
        self.assertEqual(result["status"], "conditional")
        self.assertEqual(result["rules"][0]["conditions"], "specific route only")

    def test_empty_or_partial_is_unknown(self):
        self.assertEqual(self.check([], False)["status"], "unknown")
        self.ingredients.pop("drug:2")
        self.assertEqual(self.check([])["status"], "unknown")

    def test_positive_survives_partial_coverage(self):
        result = self.check([rule()], False)
        self.assertEqual(result["status"], "contraindicated")
        self.assertFalse(result["coverage_complete"])

    def test_same_ingredient_and_all_pairs(self):
        self.ingredients["drug:2"]["codes"] = ["A"]
        self.assertEqual(self.check([rule(["A"], ["A"])])["status"], "contraindicated")
        self.products.append(product("drug:3"))
        self.assertEqual(len(compare(self.products, self.ingredients, [], False)), 3)

    def test_health_food_not_compared_as_drug(self):
        self.products[1] = product("health_food:2", "health_food")
        self.assertEqual(compare(self.products, self.ingredients, [rule()], True), [])


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings(_env_file=None)
        self.repo = MagicMock(run_id="run-1")
        self.repo.start = AsyncMock()
        self.repo.resolve = AsyncMock(return_value=([product()], True))
        self.repo.documents = AsyncMock(return_value=[{"chunk_id": "c1", "product_key": "drug:1",
                                                       "content": "fixture benefits"}])
        self.repo.safety = AsyncMock(return_value=({}, [], False))
        self.bedrock = MagicMock()
        self.bedrock.embed = AsyncMock(return_value=[0.1])
        self.bedrock.generate = AsyncMock(return_value={"answer": "fixture [E1]", "stop_reason": "end_turn",
                                                       "usage": {"inputTokens": 10, "outputTokens": 5}})
        self.service = Service(self.repo, self.bedrock, self.settings)

    def request(self, **kw):
        return AskRequest.model_validate({"question": "효능?", "intent": "efficacy",
                                          "products": [{"name": "test"}], **kw})

    async def test_similar_candidate_requires_confirmation_without_bedrock(self):
        self.repo.resolve.return_value = ([product()], False)
        result = await self.service.ask(self.request())
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.clarifications[0]["candidates"][0]["product_key"], "drug:1")
        self.bedrock.embed.assert_not_called()
        self.bedrock.generate.assert_not_called()

    async def test_absent_product_requires_question(self):
        self.repo.resolve.return_value = ([], False)
        self.assertEqual((await self.service.ask(self.request())).status, "needs_clarification")

    async def test_selected_model_and_usage(self):
        result = await self.service.ask(self.request(model="sonnet"))
        self.assertEqual(result.model_id, self.settings.sonnet_model_id)
        self.assertEqual(result.status, "answered")
        self.assertEqual(result.usage["inputTokens"], 10)
        prompt = json.loads(self.bedrock.generate.call_args.args[2])
        self.assertEqual(prompt["evidence"][0]["id"], "E1")

    async def test_missing_benefits_does_not_generate(self):
        self.repo.documents.return_value = []
        self.assertEqual((await self.service.ask(self.request())).status, "insufficient_data")
        self.bedrock.generate.assert_not_called()

    async def test_context_overflow_does_not_truncate(self):
        self.repo.documents.return_value[0]["content"] = "x" * 20000
        result = await self.service.ask(self.request())
        self.assertEqual(result.status, "insufficient_data")
        self.assertEqual(len(result.evidence[0]["content"]), 20000)
        self.bedrock.generate.assert_not_called()

    async def test_refusal_and_truncation_never_return_partial_answer(self):
        for stop, status in [("refusal", "refused"), ("max_tokens", "insufficient_data"),
                             ("content_filtered", "refused")]:
            self.bedrock.generate.return_value["stop_reason"] = stop
            result = await self.service.ask(self.request())
            self.assertEqual(result.status, status)
            self.assertNotEqual(result.answer, "fixture [E1]")

    async def test_health_food_uses_full_precautions_no_embedding(self):
        self.repo.resolve.side_effect = [([product()], True), ([product("health_food:2", "health_food")], True)]
        result = await self.service.ask(self.request(intent="interactions", products=[{"name": "a"}, {"name": "b"}]))
        self.repo.documents.assert_awaited_once_with("health_food:2", "precautions", None)
        self.bedrock.embed.assert_not_called()
        self.repo.safety.assert_not_called()
        self.assertEqual(result.interaction_checks, [])

    async def test_drug_rules_go_to_prompt_without_vector_lookup(self):
        self.repo.resolve.side_effect = [([product()], True), ([product("drug:2")], True)]
        self.repo.safety.return_value = ({"drug:1": {"codes": ["A"], "complete": True},
                                        "drug:2": {"codes": ["B"], "complete": True}}, [rule()], True)
        result = await self.service.ask(self.request(intent="interactions", products=[{"name": "a"}, {"name": "b"}]))
        self.assertEqual(result.interaction_checks[0]["status"], "contraindicated")
        self.bedrock.embed.assert_not_called()
        self.repo.documents.assert_not_called()
        prompt = json.loads(self.bedrock.generate.call_args.args[2])
        self.assertEqual(prompt["checks"][0]["rules"][0]["source"], "fixture")

    async def test_duplicate_products_reprompt(self):
        result = await self.service.ask(self.request(intent="interactions", products=[{"name": "a"}, {"name": "a"}]))
        self.assertEqual(result.status, "needs_clarification")
        self.bedrock.generate.assert_not_called()


class ApiTests(unittest.TestCase):
    def setUp(self):
        # No lifespan needed for validation-only routes, no DB/AWS connection.
        app.state.llm_settings = Settings(_env_file=None)
        self.client = TestClient(app)

    def test_swagger_and_schema(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/llm/v1/ask", schema["paths"])
        self.assertEqual(schema["components"]["schemas"]["AskRequest"]["properties"]["model"]["anyOf"][0]["enum"], ["sonnet", "haiku"])

    def test_models_and_auth(self):
        self.assertEqual(self.client.get("/llm/v1/models").status_code, 200)
        app.state.llm_settings = Settings(_env_file=None, api_key="test-secret")
        self.assertEqual(self.client.get("/llm/v1/models").status_code, 401)
        self.assertEqual(self.client.get("/llm/v1/models", headers={"X-API-Key": "test-secret"}).status_code, 200)

    def test_invalid_request_is_422(self):
        for payload in [{}, {"question": "q", "intent": "interactions", "products": [{"name": "a"}]},
                        {"question": "q", "intent": "efficacy", "products": [{"name": " "}]},
                        {"question": "q", "intent": "efficacy", "products": [{"name": "a"}], "model": "other"}]:
            self.assertEqual(self.client.post("/llm/v1/ask", json=payload).status_code, 422)

    def test_bundle_rejects_blank_codes_and_duplicates(self):
        data = {"run_id": "r", "source": "s", "products": [], "rules": [rule([" "])]}
        with self.assertRaises(ValidationError):
            SafetyBundle.model_validate(data)
        data["rules"] = [rule(), rule()]
        with self.assertRaises(ValidationError):
            SafetyBundle.model_validate(data)


class BedrockTests(unittest.IsolatedAsyncioTestCase):
    async def test_converse_payload(self):
        bedrock = Bedrock(Settings(_env_file=None))
        bedrock.client = MagicMock()
        bedrock.client.converse.return_value = {"output": {"message": {"content": [{"text": "ok"}]}},
                                                "stopReason": "end_turn", "usage": {"inputTokens": 2}}
        result = await bedrock.generate("chosen-model", "system", "prompt")
        self.assertEqual(result["answer"], "ok")
        args = bedrock.client.converse.call_args.kwargs
        self.assertEqual(args["modelId"], "chosen-model")
        self.assertEqual(args["additionalModelRequestFields"]["thinking"]["type"], "disabled")

    async def test_bad_embedding_fails_closed(self):
        bedrock = Bedrock(Settings(_env_file=None))
        bedrock.client = MagicMock()
        bedrock.client.invoke_model.return_value["body"].read.return_value = '{"embedding":[0]}'
        with self.assertRaises(ValueError):
            await bedrock.embed("test")


if __name__ == "__main__":
    unittest.main()

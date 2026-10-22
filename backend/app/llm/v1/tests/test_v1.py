import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.llm.v1.api import app
from app.llm.v1.bedrock import Bedrock
from app.llm.v1.config import Settings
from app.llm.v1.interactions import compare
from app.llm.v1.schemas import AskRequest, SafetyBundle
from app.llm.v1.service import Service
from app.llm.v1.routing import Route


def product(key="drug:1", kind="drug"):
    return {"product_key": key, "product_name": key, "product_type": kind, "manufacturer": "test", "sale_status": "판매"}


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

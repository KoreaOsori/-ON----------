import unittest
from unittest.mock import AsyncMock

from app.llm.v1.interactions import compare_gold
from app.llm.v1.repository import Repository
from app.llm.v1.routing import classify
from app.llm.v1.schemas import AskRequest


def products():
    return [{"product_key": f"drug:{i}", "product_type": "drug", "sale_status": "판매"} for i in (1, 2)]


def ingredients():
    return {f"drug:{i}": [{"ingr_key": code, "dur_ingr_code": code}] for i, code in ((1, "A"), (2, "B"))}


def rule(**changes):
    return {"id": 1, "item_seq": "1", "mixture_item_seq": "2", "basis": "품목 DUR", "source_key": "s",
            "ingr_code": "A", "mixture_ingr_code": "B", "prohbt_content": "금기 원문",
            "remark": "조건 원문", "carried_from": "2026-10-16", **changes}


class GoldComparisonTests(unittest.TestCase):
    def test_official_missing_codes_still_reports_product_dur(self):
        result = compare_gold(products(), {}, [rule()])[0]
        self.assertEqual(result["status"], "contraindicated")
        self.assertFalse(result["rules"][0]["code_match"])
        self.assertFalse(result["coverage_complete"])

    def test_ingredient_basis_is_not_official_prohibition(self):
        result = compare_gold(products(), ingredients(), [rule(basis="성분 규칙")])[0]
        self.assertEqual(result["status"], "ingredient_caution")
        self.assertTrue(result["rules"][0]["code_match"])
        self.assertEqual(result["rules"][0]["remark"], "조건 원문")

    def test_other_product_with_same_codes_is_not_applied(self):
        result = compare_gold(products(), ingredients(), [rule(item_seq="3")])[0]
        self.assertEqual(result["rules"], [])

    def test_reverse_rows_deduplicate_and_preserve_source(self):
        result = compare_gold(products(), ingredients(), [rule(), rule(id=2, item_seq="2", mixture_item_seq="1",
                                         ingr_code="B", mixture_ingr_code="A")])[0]
        self.assertEqual(len(result["rules"]), 1)
        self.assertEqual(result["rules"][0]["carried_from"], "2026-10-16")

    def test_incomplete_mapping_unknown_and_duplicates_separate(self):
        data = {key: [{"ingr_key": "shared", "dur_ingr_code": None}] for key in ingredients()}
        result = compare_gold(products(), data, [])[0]
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["duplicate_ingredients"], ["shared"])


class GoldRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_names_only_schema(self):
        request = AskRequest(question="함께 먹어도 되나요?", products=["제품A", "제품B"])
        self.assertEqual(request.products, ["제품A", "제품B"])
        self.assertNotIn("intent", AskRequest.model_json_schema()["properties"])

    async def test_start_does_not_require_vector(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock(return_value=[{"silver_snapshot": "2026-10-16", "gold_written_at": "now"}])
        await repo.start()
        self.assertTrue(repo.run_id.startswith("gold:"))
        self.assertNotIn("product_search", repo.rows.call_args.args[0])

    async def test_resolve_ambiguous_names_and_partial(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock(return_value=[{"product_key": "drug:1"}, {"product_key": "drug:2"}])
        self.assertFalse((await repo.resolve("제품"))[1])
        repo.rows.side_effect = [[], [{"product_key": "drug:1"}]]
        self.assertFalse((await repo.resolve("제품"))[1])

    async def test_health_food_precautions_from_gold(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock(return_value=[{"iftkn_atnt_matr_cn": "주의 원문"}])
        docs = await repo.documents("health_food:123", "precautions")
        self.assertEqual(docs[0]["content"], "주의 원문")
        self.assertIn("gold.health_food", repo.rows.call_args.args[0])

    async def test_safety_queries_use_gold_and_bound_product_ids(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock(side_effect=[[{"item_seq": "1", "dur_ingr_code": "A"}], [rule()]])
        data, rules = await repo.safety(["drug:1", "drug:2"])
        self.assertEqual(data["drug:1"][0]["dur_ingr_code"], "A")
        self.assertEqual(rules[0]["basis"], "품목 DUR")
        self.assertIn("gold.drug_contraindication", repo.rows.call_args.args[0])
        self.assertEqual(repo.rows.call_args.kwargs["ids"], ["1", "2"])


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_information_interactions_and_both(self):
        import json
        for intent, sections in [("information", ["usage"]), ("interactions", []), ("both", ["benefits"])]:
            bedrock = AsyncMock()
            bedrock.generate.return_value = {"answer": json.dumps({"intent": intent, "sections": sections}),
                                              "stop_reason": "end_turn", "usage": {"inputTokens": 10}}
            route, usage = await classify(bedrock, "model", "질문")
            self.assertEqual(route.intent, intent)
            self.assertEqual(usage["inputTokens"], 10)
            self.assertEqual(bedrock.generate.call_args.kwargs["max_tokens"], 500)

    async def test_invalid_classifier_response_requires_question(self):
        for answer in ('not json', '{"intent":"information","sections":[]}',
                       '{"intent":"information","sections":["invented"]}'):
            bedrock = AsyncMock()
            bedrock.generate.return_value = {"answer": answer, "stop_reason": "end_turn", "usage": {}}
            route, _ = await classify(bedrock, "model", "질문")
            self.assertEqual(route.intent, "clarify")

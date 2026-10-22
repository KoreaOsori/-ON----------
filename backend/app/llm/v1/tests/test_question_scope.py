import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.llm.v1.routing import Route, classify, scoped_question


class QuestionScopeTests(unittest.TestCase):
    def test_removes_only_excluded_names_preserving_patient_context(self):
        route = Route(intent='information', sections=['precautions'], product_names=['약B'],
                      excluded_product_names=['약A'])
        question = '약A는 제외하고 임신 12주인데 약B 주의사항은? 약A 말고요.'
        result = scoped_question(question, route, ['약B'])
        self.assertNotIn('약A', result)
        self.assertIn('임신 12주인데 약B 주의사항은?', result)

    def test_active_longer_names_are_not_corrupted(self):
        route = Route(intent='information', sections=['benefits'], excluded_product_names=['약A'])
        result = scoped_question('약A 제외, 약A플러스 효능?', route, ['약A플러스'])
        self.assertIn('약A플러스 효능?', result)
        self.assertNotIn('약A 제외', result)

    def test_explicit_product_list_is_preserved(self):
        route = Route(intent='information', sections=['benefits'], excluded_product_names=['약A'])
        self.assertEqual(scoped_question('약A 효능?', route, ['약A']), '약A 효능?')

    def test_no_exclusions_preserves_future_use_question(self):
        route = Route(intent='interactions', sections=[], product_names=['약A', '약B'])
        question = '약A는 아직 안 먹는데 약B와 같이 먹어도 되나요?'
        self.assertEqual(scoped_question(question, route, route.product_names), question)


class ClassificationScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_validates_excluded_mentions_and_conflicts(self):
        for excluded, expected in [(['약A'], 'information'), (['없는약'], 'clarify'), (['약B'], 'clarify')]:
            with self.subTest(excluded=excluded):
                bedrock = MagicMock()
                bedrock.generate = AsyncMock(return_value={
                    'stop_reason': 'end_turn', 'usage': {},
                    'answer': json.dumps({'intent': 'information', 'sections': ['benefits'],
                                          'product_names': ['약B'], 'excluded_product_names': excluded})})
                route, _ = await classify(bedrock, 'model', '약A 제외하고 약B 효능만')
                self.assertEqual(route.intent, expected)

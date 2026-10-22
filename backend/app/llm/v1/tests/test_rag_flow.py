import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.llm.v1.config import Settings
from app.llm.v1.repository import Repository
from app.llm.v1.routing import Route, classify
from app.llm.v1.schemas import AskRequest
from app.llm.v1.service import Service


def product(key, name, kind='drug'):
    return {'product_key': key, 'product_name': name, 'product_type': kind, 'manufacturer': '회사', 'sale_status': '판매'}


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = MagicMock(run_id='gold:test', vector_warning=None)
        self.repo.start = AsyncMock()
        self.repo.prepare_vectors = AsyncMock(return_value=True)
        self.repo.resolve = AsyncMock()
        self.repo.documents = AsyncMock(return_value=[{'product_key': 'health_food:2', 'content': '원문 주의사항',
                                                      'source': 'gold.health_food.iftkn_atnt_matr_cn'}])
        self.repo.vector_candidates = AsyncMock(return_value=[])
        self.repo.vector_documents = AsyncMock(return_value=[])
        self.repo.safety = AsyncMock(return_value=({}, []))
        self.bedrock = MagicMock()
        self.bedrock.embed = AsyncMock(return_value=[0.1])
        self.bedrock.generate = AsyncMock(return_value={'answer': '근거 답변', 'usage': {}, 'stop_reason': 'end_turn'})
        self.route = Route(intent='interactions', sections=[], product_names=['영양제B'])
        patcher = patch('app.llm.v1.service.classify', new_callable=AsyncMock)
        self.classifier = patcher.start()
        self.classifier.return_value = (self.route, {})
        self.addCleanup(patcher.stop)
        self.service = Service(self.repo, self.bedrock, Settings(_env_file=None))

    async def test_question_name_merged_and_mixed_pair_uses_gold_only(self):
        self.repo.resolve.side_effect = [([product('drug:1', '약A')], True),
                                         ([product('health_food:2', '영양제B', 'health_food')], True)]
        result = await self.service.ask(AskRequest(question='영양제B와 같이?', products=['약A']))
        self.assertEqual(result.merged_product_names, ['약A', '영양제B'])
        self.repo.safety.assert_not_called()
        self.repo.documents.assert_awaited_once_with('health_food:2', 'precautions')
        self.bedrock.embed.assert_not_called()
        self.assertEqual(result.interaction_checks, [])
        self.assertIn('원문 주의사항', self.bedrock.generate.call_args.args[2])

    async def test_fuzzy_vector_candidates_are_not_automatically_selected(self):
        self.route.intent = 'information'
        self.route.sections = ['benefits']
        self.repo.resolve.return_value = ([], False)
        self.repo.vector_candidates.return_value = [product('health_food:2', '영양제비', 'health_food')]
        result = await self.service.ask(AskRequest(question='영양제B 효능?'))
        self.assertEqual(result.status, 'needs_clarification')
        self.assertIn('영양제비', result.answer)
        self.assertEqual(result.clarifications[0]['candidates'][0]['product_key'], 'health_food:2')
        self.bedrock.generate.assert_not_called()

    async def test_question_candidate_can_be_selected_by_name(self):
        self.route.intent, self.route.sections = 'information', ['benefits']
        self.repo.resolve.return_value = ([product('health_food:2', '영양제비', 'health_food')], True)
        result = await self.service.ask(AskRequest(question='영양제B 효능?', name_selections={'영양제B': 'health_food:2'}))
        self.repo.resolve.assert_awaited_once_with('영양제B', 'health_food:2')
        self.assertEqual(result.status, 'answered')

    async def test_duplicate_mentions_do_not_duplicate_products(self):
        self.route.intent, self.route.sections = 'information', ['benefits']
        self.repo.resolve.return_value = ([product('drug:1', '영양제B')], True)
        result = await self.service.ask(AskRequest(question='영양제B 효능?', products=['영양제B', '영양제B']))
        self.assertEqual(result.merged_product_names, ['영양제B'])
        self.repo.resolve.assert_awaited_once()

    async def test_scoped_vector_evidence_used_for_information(self):
        self.route.intent, self.route.sections = 'information', ['benefits']
        self.repo.resolve.return_value = ([product('drug:1', '영양제B')], True)
        self.repo.vector_documents.return_value = [{'product_key': 'drug:1', 'content': '벡터 근거',
                                                   'source': 'product_search.product_vectors'}]
        result = await self.service.ask(AskRequest(question='영양제B 효능?'))
        self.repo.vector_documents.assert_awaited_once_with('drug:1', 'benefits', [0.1])
        self.assertEqual(result.evidence[0]['content'], '벡터 근거')

    async def test_empty_question_names_reprompt_and_no_db(self):
        self.route.product_names = []
        result = await self.service.ask(AskRequest(question='같이 먹어도 되나요?'))
        self.assertEqual(result.status, 'needs_clarification')
        self.repo.start.assert_not_called()

    async def test_over_eight_merged_products_reprompt(self):
        result = await self.service.ask(AskRequest(question='영양제B와 같이?', products=[f'약{i}' for i in range(8)]))
        self.assertEqual(result.status, 'needs_clarification')
        self.repo.start.assert_not_called()


class ExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracted_names_follow_question_order(self):
        bedrock = MagicMock()
        bedrock.generate = AsyncMock(return_value={'stop_reason': 'end_turn', 'usage': {}, 'answer': json.dumps({
            'intent': 'interactions', 'sections': [], 'product_names': ['영양제B', '약A', '약A']})})
        route, _ = await classify(bedrock, 'model', '약A와 영양제B를 같이 먹나요?')
        self.assertEqual(route.product_names, ['약A', '영양제B'])

    async def test_hallucinated_name_forces_clarification(self):
        bedrock = MagicMock()
        bedrock.generate = AsyncMock(return_value={'stop_reason': 'end_turn', 'usage': {}, 'answer': json.dumps({
            'intent': 'interactions', 'sections': [], 'product_names': ['존재하지않는이름']})})
        route, _ = await classify(bedrock, 'model', '이 약과 같이 먹나요?')
        self.assertEqual(route.intent, 'clarify')


class VectorRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_vectors_report_fallback(self):
        repo = Repository(None, Settings(_env_file=None))
        repo.rows = AsyncMock(return_value=[{'config': None, 'active': None, 'runs': None,
                                           'links': None, 'vectors': None, 'trgm': False}])
        self.assertFalse(await repo.prepare_vectors())
        self.assertIn('gold', repo.vector_warning)

    async def test_snapshot_mismatch_is_not_used(self):
        settings = Settings(_env_file=None)
        repo = Repository(None, settings)
        repo.gold_snapshot = '2026-10-22'
        repo.rows = AsyncMock(side_effect=[
            [{'config': 'c', 'active': 'a', 'runs': 'r', 'links': 'l', 'vectors': 'v', 'trgm': True}],
            [{'schema_version': 2, 'embedding_version': settings.embedding_version, 'dimensions': settings.embedding_dimensions}],
            [{'run_id': 'old', 'snapshot': '2026-10-16'}]])
        self.assertFalse(await repo.prepare_vectors())
        self.assertIsNone(repo.vector_run)

    async def test_vector_documents_filter_product_section_and_run(self):
        repo = Repository(None, Settings(_env_file=None))
        repo.vector_run = 'run'
        repo.rows = AsyncMock(return_value=[])
        await repo.vector_documents('drug:1', 'benefits', [0.1])
        self.assertEqual(repo.rows.call_args.kwargs['key'], 'drug:1')
        self.assertEqual(repo.rows.call_args.kwargs['section'], 'benefits')
        self.assertEqual(repo.rows.call_args.kwargs['run'], 'run')

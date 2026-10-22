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

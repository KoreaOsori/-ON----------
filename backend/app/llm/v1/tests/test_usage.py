import asyncio
import io
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.llm.v1.usage import Usage
from app.llm.v1.service import Service
from app.llm.v1.config import Settings
from app.llm.v1.bedrock import Bedrock


class UsageTests(unittest.TestCase):
    def test_totals_include_routing_embedding_and_both_answer_attempts(self):
        usage = Usage()
        usage.add('routing', {'inputTokens': 10, 'outputTokens': 2, 'totalTokens': 12, 'cacheReadInputTokens': 4})
        usage.add('embedding', {'inputTokens': 3, 'outputTokens': 0, 'totalTokens': 3})
        usage.add('answer', {'inputTokens': 30, 'outputTokens': 20, 'totalTokens': 50})
        usage.add('answer', {'inputTokens': 31, 'outputTokens': 10, 'totalTokens': 41, 'cacheWriteInputTokens': 7})
        result = usage.snapshot()
        self.assertEqual((result['inputTokens'], result['outputTokens'], result['totalTokens']), (74, 32, 106))
        self.assertEqual(result['answer']['calls'], 2)
        self.assertEqual(result['calls'], 4)
        self.assertEqual(result['cacheReadInputTokens'], 4)
        self.assertEqual(result['cacheWriteInputTokens'], 7)
        self.assertTrue(result['complete'])

    def test_missing_usage_is_unknown_not_free(self):
        usage = Usage()
        usage.add('routing', {'inputTokens': 10, 'outputTokens': 2})
        usage.add('answer', {})
        self.assertIsNone(usage.snapshot()['totalTokens'])
        self.assertFalse(usage.snapshot()['complete'])
        self.assertEqual(usage.snapshot()['routing']['totalTokens'], 12)
        self.assertEqual(usage.snapshot()['embedding']['calls'], 0)


class UsageFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_rewrite_and_refusal_are_both_counted(self):
        bedrock = MagicMock()
        bedrock.generate = AsyncMock(side_effect=[
            {'answer': 'partial', 'stop_reason': 'max_tokens', 'usage': {'inputTokens': 20, 'outputTokens': 10}},
            {'answer': '', 'stop_reason': 'refusal', 'usage': {'inputTokens': 25, 'outputTokens': 1}}])
        service = Service(None, bedrock, Settings(_env_file=None))
        service.usage.add('routing', {'inputTokens': 10, 'outputTokens': 2})
        response = await service.respond('model', {}, 'answered', {'question': '질문'})
        self.assertEqual(response.status, 'refused')
        self.assertEqual(response.usage['totalTokens'], 68)
        self.assertEqual(response.usage['answer']['calls'], 2)

    async def test_embedding_reports_provider_token_count_and_closes_body(self):
        bedrock = Bedrock(Settings(_env_file=None))
        body = io.BytesIO(json.dumps({'embedding': [0.1] * 1024, 'inputTextTokenCount': 17}).encode())
        bedrock.client = MagicMock()
        bedrock.client.invoke_model.return_value = {'body': body}
        vector, usage = await bedrock.embed_with_usage('질문')
        self.assertEqual(len(vector), 1024)
        self.assertEqual(usage['totalTokens'], 17)
        self.assertTrue(body.closed)

    async def test_concurrent_services_do_not_share_usage(self):
        bedrock = MagicMock()
        bedrock.generate = AsyncMock(return_value={'answer': '답변', 'stop_reason': 'end_turn',
                                                   'usage': {'inputTokens': 2, 'outputTokens': 1}})
        a, b = [Service(None, bedrock, Settings(_env_file=None)) for _ in range(2)]
        a.usage.add('routing', {'inputTokens': 10, 'outputTokens': 2})
        b.usage.add('routing', {'inputTokens': 20, 'outputTokens': 2})
        results = await asyncio.gather(a.respond('m', {}, 'answered', {}), b.respond('m', {}, 'answered', {}))
        self.assertEqual([r.usage['totalTokens'] for r in results], [15, 25])

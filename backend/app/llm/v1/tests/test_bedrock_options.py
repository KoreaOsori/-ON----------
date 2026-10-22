import unittest
from unittest.mock import MagicMock

from app.llm.v1.bedrock import Bedrock
from app.llm.v1.config import Settings


class BedrockOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_options_and_token_budgets(self):
        settings = Settings(_env_file=None)
        bedrock = Bedrock(settings)
        bedrock.client = MagicMock()
        bedrock.client.converse.return_value = {
            'stopReason': 'end_turn',
            'output': {'message': {'content': [{'text': '답변'}]}},
            'usage': {'outputTokens': 2},
        }
        for alias, thinking in [('sonnet', 'between_tools'), ('haiku', 'disabled')]:
            for budget in (500, None):
                with self.subTest(model=alias, budget=budget):
                    result = await bedrock.generate(settings.model_id(alias), '규칙', '질문', max_tokens=budget)
                    args = bedrock.client.converse.call_args.kwargs
                    self.assertEqual(args['modelId'], settings.model_id(alias))
                    self.assertEqual(args['additionalModelRequestFields'], {'thinking': {'type': thinking}})
                    self.assertEqual(args['inferenceConfig']['maxTokens'], budget or settings.max_output_tokens)
                    self.assertEqual(result, {'answer': '답변', 'stop_reason': 'end_turn', 'usage': {'outputTokens': 2}})

    async def test_configured_sonnet_profile_uses_between_tools(self):
        settings = Settings(_env_file=None, sonnet_model_id='arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/test')
        bedrock = Bedrock(settings)
        bedrock.client = MagicMock()
        bedrock.client.converse.return_value = {}
        await bedrock.generate(settings.model_id('sonnet'), '규칙', '질문')
        self.assertEqual(bedrock.client.converse.call_args.kwargs['additionalModelRequestFields'],
                         {'thinking': {'type': 'between_tools'}})

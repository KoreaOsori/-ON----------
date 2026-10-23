import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.llm.v1.api import create_app
from app.llm.v1.config import Settings
from app.llm.v1.repository import Repository
from app.llm.v1.routing import Route
from app.llm.v1.schemas import AskRequest, AskResponse
from app.llm.v1.service import Service


def product(key='drug:1', name='약A', kind='drug'):
    return {'product_key': key, 'product_name': name, 'product_type': kind, 'sale_status': '판매'}


class FriendlyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = MagicMock(run_id='gold:test', vector_warning=None)
        self.repo.start = AsyncMock()
        self.repo.resolve = AsyncMock(return_value=([product()], True))
        self.repo.prepare_vectors = AsyncMock(return_value=True)
        self.repo.documents = AsyncMock(return_value=[{'product_key': 'drug:1', 'content': '효능 원문'}])
        self.repo.vector_documents = AsyncMock(return_value=[])
        self.repo.safety = AsyncMock(return_value=({}, []))
        self.repo.ingredient_rules = AsyncMock(return_value=[])
        self.repo.dur_ingredient_rules = AsyncMock(return_value=[])
        self.bedrock = MagicMock()
        self.bedrock.embed = AsyncMock(return_value=[0.1])
        self.bedrock.generate = AsyncMock(return_value={'answer': '친절한 모델 답변', 'usage': {'outputTokens': 20}, 'stop_reason': 'end_turn'})
        self.route = Route(intent='information', sections=['benefits'], product_names=[])
        patcher = patch('app.llm.v1.service.classify', new_callable=AsyncMock)
        self.classifier = patcher.start()
        self.classifier.return_value = (self.route, {'inputTokens': 10})
        self.addCleanup(patcher.stop)
        self.service = Service(self.repo, self.bedrock, Settings(_env_file=None))

    def request(self, **kwargs):
        return AskRequest(**{'question': '효능?', 'products': ['약A'], **kwargs})

    def payload(self):
        return json.loads(self.bedrock.generate.call_args.args[2])

    async def test_response_exactly_three_fields(self):
        response = await self.service.ask(self.request())
        self.assertEqual(set(response.model_dump()), {'status', 'answer', 'usage'})
        self.assertEqual(response.answer, '친절한 모델 답변')
        self.assertEqual(response.usage['routing']['inputTokens'], 10)
        self.assertEqual(response.usage, {'routing': {'inputTokens': 10}})

    async def test_uncertain_names_sent_to_llm_without_candidates(self):
        self.repo.resolve.side_effect = [([], False), ([product('drug:2', '다른 후보')], False)]
        self.route.product_names = ['질문이름']
        response = await self.service.ask(self.request(question='질문이름과 같이?', products=['불분명']))
        self.assertEqual(response.status, 'needs_clarification')
        self.assertEqual(self.payload()['unresolved'], ['불분명', '질문이름'])
        self.assertNotIn('다른 후보', self.bedrock.generate.call_args.args[2])
        self.assertNotIn('candidates', self.payload())
        self.repo.prepare_vectors.assert_not_called()
        self.bedrock.embed.assert_not_called()
        self.repo.safety.assert_not_called()

    async def test_names_merge_and_deduplicate(self):
        self.route.product_names = ['약A']
        await self.service.ask(self.request(question='약A 효능?', products=['약A', '약A']))
        self.repo.resolve.assert_awaited_once_with('약A')

    async def test_clarification_preserves_confirmed_names(self):
        self.repo.resolve.side_effect = [([product()], True), ([], False)]
        response = await self.service.ask(self.request(products=['약A', '알수없는약123']))
        self.assertEqual(response.status, 'needs_clarification')
        self.assertEqual(self.payload()['confirmed_product_names'], ['약A'])
        self.assertEqual(self.payload()['unresolved'], ['알수없는약123'])
        self.repo.safety.assert_not_called()

    async def test_excluded_question_product_is_not_looked_up(self):
        self.route.product_names = ['약A']
        self.route.excluded_product_names = ['가짜약123']
        await self.service.ask(self.request(
            question='가짜약123은 복용하지 않아요. 약A 효능만 알려주세요.', products=[]))
        self.repo.resolve.assert_awaited_once_with('약A')
        self.assertEqual([p['product_name'] for p in self.payload()['products']], ['약A'])
        self.assertNotIn('unresolved', self.payload())
        self.assertNotIn('가짜약123', self.bedrock.generate.call_args.args[2])
        self.assertNotIn('가짜약123', self.bedrock.embed.call_args.args[0])
        self.assertIn('조회했다고 주장하지 마라', self.bedrock.generate.call_args.args[1])

    async def test_truncated_answer_rewritten_once_from_full_evidence(self):
        self.repo.documents.return_value[0]['content'] = '주의 원문과 예외 조건'
        self.bedrock.generate.side_effect = [
            {'answer': '잘린 답변', 'stop_reason': 'max_tokens'},
            {'answer': '완성된 답변', 'stop_reason': 'end_turn'},
        ]
        response = await self.service.ask(self.request())
        self.assertEqual(response.status, 'answered')
        self.assertEqual(response.answer, '완성된 답변')
        self.assertEqual(response.usage, {'routing': {'inputTokens': 10}})
        first, retry = self.bedrock.generate.await_args_list
        self.assertEqual(first.args[2], retry.args[2])
        self.assertIn('주의 원문과 예외 조건', retry.args[2])
        self.assertNotIn('잘린 답변', retry.args[2])
        self.repo.resolve.assert_awaited_once()

    async def test_retry_is_bounded_and_never_returns_partial_answer(self):
        self.bedrock.generate.return_value = {'answer': '잘린 답변', 'stop_reason': 'max_tokens'}
        response = await self.service.ask(self.request())
        self.assertEqual(self.bedrock.generate.await_count, 2)
        self.assertEqual(response.status, 'insufficient_data')
        self.assertNotIn('잘린 답변', response.answer)

    async def test_refusal_does_not_retry(self):
        self.bedrock.generate.return_value = {'answer': '거절', 'stop_reason': 'refusal'}
        response = await self.service.ask(self.request())
        self.assertEqual(response.status, 'refused')
        self.bedrock.generate.assert_awaited_once()

    async def test_mixed_pair_gold_precautions_without_ingredient_comparison(self):
        self.route.intent, self.route.sections, self.route.product_names = 'interactions', [], ['영양제B']
        self.repo.resolve.side_effect = [([product()], True), ([product('health_food:2', '영양제B', 'health_food')], True)]
        self.repo.documents.return_value = [{'product_key': 'health_food:2', 'content': '섭취 주의사항 전체'}]
        response = await self.service.ask(self.request(question='영양제B와 같이?'))
        self.assertEqual(response.status, 'answered')
        self.repo.documents.assert_awaited_once_with('health_food:2', 'precautions')
        self.repo.safety.assert_not_called()
        self.repo.dur_ingredient_rules.assert_not_called()
        self.bedrock.embed.assert_not_called()
        self.assertIn('섭취 주의사항 전체', self.bedrock.generate.call_args.args[2])

    async def test_new_dur_rules_reach_answer_prompt(self):
        self.route.intent, self.route.sections = 'interactions', []
        self.repo.resolve.side_effect = [([dict(product(), route='경구')], True),
                                        ([dict(product('drug:2', '약B'), route='경구')], True)]
        ingredients = {'drug:1': [{'ingr_key': 'A', 'dur_ingr_code': 'A'}],
                       'drug:2': [{'ingr_key': 'B', 'dur_ingr_code': 'B'}]}
        self.repo.safety.return_value = (ingredients, [])
        self.repo.dur_ingredient_rules.return_value = [
            dict(caution_type='효능군중복', mix_type='단일', sers_name='계열', ingr_code=code, ingr_name=code)
            for code in ('A', 'B')]
        await self.service.ask(self.request(products=['약A', '약B']))
        self.repo.dur_ingredient_rules.assert_awaited_once_with(ingredients)
        self.assertEqual(self.payload()['checks'][0]['therapeutic_duplications'][0]['verdict'], 'duplicate_caution')
        self.assertEqual(self.payload()['checks'][0]['product_pair_result'], 'not_found')

    async def test_vector_information_still_used(self):
        self.repo.vector_documents.return_value = [{'product_key': 'drug:1', 'content': '벡터 근거'}]
        await self.service.ask(self.request())
        self.repo.vector_documents.assert_awaited_once_with('drug:1', 'benefits', [0.1])
        self.assertEqual(self.payload()['evidence'][0]['text'], '벡터 근거')

    async def test_three_product_overview_uses_short_gold_and_vector_evidence(self):
        self.route.overview = True
        self.route.product_names = ['코푸시럽', '셉트린정', '코데농정']
        names = ['코데농정', '코푸시럽', '셉트린정']
        self.repo.resolve.side_effect = [([product(f'drug:{i}', name)], True) for i, name in enumerate(names)]
        async def documents(key, section):
            self.assertEqual(section, 'benefits')
            return [{'product_key': key, 'content': '긴 효능 원문' * 5000, 'source': 'gold.drug.doc_efficacy'},
                    {'product_key': key, 'content': key + ' 짧은 효능 원문', 'source': 'gold.drug.easy_efcy'}]
        async def vectors(key, section, vector):
            return [{'product_key': key, 'content': key + ' 벡터 보조 근거'}]
        self.repo.documents.side_effect = documents
        self.repo.vector_documents.side_effect = vectors
        response = await self.service.ask(self.request(
            question='코푸시럽, 셉트린정, 코데농정 해당 약품에 대해 설명해줘요', products=['코데농정']))
        self.assertEqual(response.status, 'answered')
        self.assertEqual(self.repo.resolve.await_count, 3)
        self.assertTrue(self.payload()['overview'])
        self.assertEqual(len(self.payload()['evidence']), 6)
        self.assertLess(len(self.bedrock.generate.call_args.args[2]), self.service.settings.context_chars)
        self.assertEqual(self.repo.vector_documents.await_count, 3)
        self.repo.safety.assert_not_called()

    async def test_overview_missing_one_product_keeps_other_evidence(self):
        self.route.overview = True
        self.repo.resolve.side_effect = [([product()], True), ([product('drug:2', '약B')], True)]
        self.repo.documents.side_effect = [[{'product_key': 'drug:1', 'content': '확인된 효능'}], []]
        response = await self.service.ask(self.request(products=['약A', '약B']))
        self.assertEqual(response.status, 'insufficient_data')
        self.assertEqual(self.payload()['evidence'][0]['text'], '확인된 효능')
        self.assertEqual(self.payload()['limitations'][0]['missing_information'][0]['product'], '약B')

    async def test_detailed_precautions_keep_whole_document(self):
        self.route.sections = ['precautions']
        self.repo.documents.return_value = [{'product_key': 'drug:1', 'content': '주의 및 예외 조건 원문'}]
        await self.service.ask(self.request(question='약A 상세 주의사항은?'))
        self.assertNotIn('overview', self.payload())
        self.assertEqual(self.payload()['evidence'][0]['text'], '주의 및 예외 조건 원문')

    async def test_missing_evidence_gets_llm_explanation(self):
        self.repo.documents.return_value = []
        response = await self.service.ask(self.request())
        self.assertEqual(response.status, 'insufficient_data')
        self.assertEqual(response.answer, '친절한 모델 답변')
        self.assertTrue(self.payload()['limitations'])

    async def test_official_dur_is_passed_to_llm(self):
        self.route.intent, self.route.sections = 'interactions', []
        self.repo.resolve.side_effect = [([product()], True), ([product('drug:2', '약B')], True)]
        self.repo.safety.return_value = ({'drug:1': [{'ingr_key': 'A', 'dur_ingr_code': 'A'}],
                                        'drug:2': [{'ingr_key': 'B', 'dur_ingr_code': 'B'}]},
            [{'item_seq': '1', 'mixture_item_seq': '2', 'basis': '품목 DUR', 'source_key': 's',
              'ingr_code': 'A', 'mixture_ingr_code': 'B', 'prohbt_content': '금기 원문', 'remark': '예외 원문'}])
        response = await self.service.ask(self.request(products=['약A', '약B']))
        self.assertEqual(response.status, 'answered')
        self.assertEqual(self.payload()['checks'][0]['status'], 'contraindicated')
        self.assertEqual(self.payload()['checks'][0]['rules'][0]['remark'], '예외 원문')

    async def test_no_product_rule_is_explained_even_with_missing_codes(self):
        self.route.intent, self.route.sections = 'interactions', []
        self.repo.resolve.side_effect = [([product()], True), ([product('drug:2', '약B')], True)]
        self.repo.documents.return_value = []
        self.repo.prepare_vectors.return_value = False
        self.repo.vector_warning = 'vector not ready'
        response = await self.service.ask(self.request(products=['약A', '약B']))
        self.assertEqual(response.status, 'answered')
        self.assertEqual(self.payload()['checks'][0]['product_pair_result'], 'not_found')
        self.assertTrue(self.payload()['checks'][0]['mapping_coverage']['drug:1']['missing_ingredient_rows'])
        self.assertNotIn('vector not ready', self.bedrock.generate.call_args.args[2])

    async def test_over_budget_asks_llm_for_narrower_scope(self):
        self.repo.documents.return_value[0]['content'] = 'x' * 20000
        response = await self.service.ask(self.request())
        self.assertEqual(response.status, 'insufficient_data')
        self.assertNotIn('evidence', self.payload())
        self.assertIn('줄이도록', self.payload()['task'])

    async def test_refusal_and_partial_outputs_are_not_published(self):
        for stop, expected in [('refusal', 'refused'), ('max_tokens', 'insufficient_data')]:
            self.bedrock.generate.return_value['stop_reason'] = stop
            response = await self.service.ask(self.request())
            self.assertEqual(response.status, expected)
            self.assertNotEqual(response.answer, '친절한 모델 답변')

    async def test_no_product_name_requests_clarification_through_model(self):
        response = await self.service.ask(self.request(products=[]))
        self.assertEqual(response.status, 'needs_clarification')
        self.bedrock.generate.assert_awaited_once()
        self.repo.start.assert_not_called()

    async def test_exact_name_only_repository(self):
        repo = Repository(None, Settings(_env_file=None))
        repo.rows = AsyncMock(return_value=[])
        self.assertEqual(await repo.resolve('오타이름'), ([], False))
        repo.rows.assert_awaited_once()
        self.assertNotIn('similarity', repo.rows.call_args.args[0])


class ContractTests(unittest.TestCase):
    def test_schema_and_error_envelopes(self):
        app = create_app()
        app.state.llm_settings = Settings(_env_file=None)
        client = TestClient(app)
        schema = client.get('/openapi.json').json()
        self.assertEqual(set(schema['components']['schemas']['AskResponse']['properties']), {'status', 'answer', 'usage'})
        self.assertNotIn('name_selections', schema['components']['schemas']['AskRequest']['properties'])
        for response in [client.post('/ask', json={}), client.get('/missing')]:
            self.assertEqual(set(response.json()), {'status', 'answer', 'usage'})
            self.assertEqual(response.json()['status'], 'error')

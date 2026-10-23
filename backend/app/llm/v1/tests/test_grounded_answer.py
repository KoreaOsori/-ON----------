import unittest

from app.llm.v1.grounded_answer import render_interactions, interaction_blocks
from app.llm.v1.interactions import compare_gold


class GroundedTests(unittest.TestCase):
    def test_short_answer_keeps_comparison_limits_and_omits_unsolicited_dose(self):
        products = [dict(product_key=f'drug:{i}', product_name=f'약{i}', product_type='drug', route='경구') for i in (1, 2)]
        ingredients = {'drug:1': [dict(ingr_key='A', ingr_name='성분A', dur_ingr_code='A')],
                       'drug:2': [dict(ingr_key='B', ingr_name='성분B', dur_ingr_code=None)]}
        dose = dict(caution_type='용량주의', mix_type='단일', ingr_code='A', ingr_name='성분A',
                    max_qty='24밀리그램', form_name='정제', route='경구')
        payload = dict(question='같이 먹어도 되나요?', products=products,
                       checks=compare_gold(products, ingredients, [], dur_rules=[dose]))
        answer = render_interactions(interaction_blocks(payload), {})
        self.assertIn('성분은 확인했지만', answer)
        self.assertIn('성분끼리 비교하지 못했어요', answer)
        self.assertNotIn('성분 자료를 찾지 못해', answer)
        self.assertNotIn('24밀리그램', answer)
        self.assertNotIn('코드', answer)
        self.assertLess(len(answer), 400)
        payload['question'] = '병용할 때 최대 용량도 알려주세요'
        answer = render_interactions(interaction_blocks(payload), {})
        self.assertIn('24밀리그램', answer)
        self.assertIn('제형: 정제', answer)
        self.assertIn('개인 권장량이나 제품별 상한으로 사용하면 안 돼요', answer)

    def test_model_cannot_add_or_omit_medical_claims(self):
        blocks = ['제품쌍 비교 사실', '미확인 이유와 조건']
        for answer in ('세 제품 모두 감기약. 한 가지만 복용하세요',
                       '{"order":[0]}', '{"order":[0,0]}', '{"order":[0,9]}',
                       '{"order":[0,1],"advice":"중단하세요"}', '{"order":null}'):
            with self.subTest(answer=answer):
                result = render_interactions(blocks, {'answer': answer, 'stop_reason': 'end_turn'})
                self.assertIn(blocks[0], result)
                self.assertIn(blocks[1], result)
                self.assertNotIn('감기약', result)
                self.assertNotIn('중단하세요', result)
        result = render_interactions(blocks, {'answer': '{"order":[1,0]}', 'stop_reason': 'end_turn'})
        self.assertLess(result.index(blocks[1]), result.index(blocks[0]))

    def test_partial_model_output_falls_back_to_complete_facts(self):
        result = render_interactions(['조건 원문'], {'answer': '{"order":', 'stop_reason': 'max_tokens'})
        self.assertIn('조건 원문', result)

    def test_drug_label_and_official_exception_cannot_be_dropped(self):
        products = [dict(product_key=f'drug:{i}', product_name=f'약{i}', product_type='drug') for i in (1, 2)]
        rule = dict(item_seq='1', mixture_item_seq='2', basis='품목 DUR', source_key='test',
                    prohbt_content='금기 조건', remark='제형 예외')
        payload = dict(products=products, checks=compare_gold(products, {}, [rule]),
                       evidence=[dict(product_key='drug:1', text='주의 원문과 예외 전체')])
        text = render_interactions(interaction_blocks(payload), {})
        for expected in ('금기 조건', '제형 예외', '주의 원문과 예외 전체', '성분 자료를 찾지 못해'):
            self.assertIn(expected, text)

import unittest

from app.llm.v1.grounded_answer import render_interactions, interaction_blocks
from app.llm.v1.interactions import compare_gold


class GroundedTests(unittest.TestCase):
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

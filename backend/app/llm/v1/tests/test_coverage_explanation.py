import unittest

from app.llm.v1.interactions import compare_gold, ingredient_coverage


def row(code):
    return {'ingr_key': '성분', 'ingr_name': '성분', 'dur_ingr_code': code}


class CoverageExplanationTests(unittest.TestCase):
    def test_missing_zero_partial_and_all_are_distinct(self):
        cases = [([], 'missing', 0, '성분 자료를 찾지 못해'),
                 ([row(None)], 'none', 0, '성분은 0개'),
                 ([row(None), row('A')], 'partial', 1, '2개 중 1개만'),
                 ([row('A'), row('B')], 'all_available', 2, '조회된 성분 2개 모두')]
        for rows, state, coded, wording in cases:
            with self.subTest(state=state):
                result = ingredient_coverage({'product_name': '제품A'}, rows)
                self.assertEqual(result['mapping_state'], state)
                self.assertEqual(result['coded_count'], coded)
                self.assertEqual(result['ingredient_count'], len(rows))
                self.assertIn(wording, result['explanation'])
                self.assertNotIn('안전', result['explanation'])

    def test_zero_and_partial_pair_keeps_individual_coverage_and_official_rule(self):
        products = [{'product_key': 'drug:1', 'product_name': '제품A', 'product_type': 'drug'},
                    {'product_key': 'drug:2', 'product_name': '제품B', 'product_type': 'drug'}]
        ingredients = {'drug:1': [row(None), row(None)],
                       'drug:2': [row('A'), row(None), row(None)]}
        rule = {'item_seq': '1', 'mixture_item_seq': '2', 'basis': '품목 DUR',
                'source_key': 'test', 'prohbt_content': '금기 조건', 'remark': '예외 조건'}
        for rules in ([], [rule]):
            with self.subTest(official=bool(rules)):
                result = compare_gold(products, ingredients, rules)[0]
                coverage = result['mapping_coverage']
                self.assertEqual(coverage['drug:1']['mapping_state'], 'none')
                self.assertEqual(coverage['drug:2']['mapping_state'], 'partial')
                self.assertIn('제품A: 조회된 성분 2개', coverage['drug:1']['explanation'])
                self.assertIn('제품B: 조회된 성분 3개 중 1개만', coverage['drug:2']['explanation'])
                self.assertEqual(result['ingredient_pair_result'], 'not_checkable')
                self.assertEqual(result['product_pair_result'], 'contraindicated' if rules else 'not_found')
                if rules:
                    self.assertEqual(result['rules'][0]['remark'], '예외 조건')

import unittest
from unittest.mock import AsyncMock

from app.llm.v1.interactions import compare_gold
from app.llm.v1.repository import Repository


def row(name, code):
    return dict(ingr_name=name, ingr_key=name, dur_ingr_code=code)


class PairExplanationTests(unittest.TestCase):
    def test_three_products_keep_partial_and_unavailable_pairs_separate(self):
        products = [dict(product_key=f'drug:{i}', product_name=name, product_type='drug', sale_status='판매')
                    for i, name in enumerate(['제품A', '제품B', '제품C'])]
        ingredients = {'drug:0': [row('공통1', 'A'), row('공통2', 'B'), row('미연결1', None)],
                       'drug:1': [row('공통1', 'A'), row('공통2', 'B'), row('미연결2', None)],
                       'drug:2': [row('미연결3', None)]}
        checks = compare_gold(products, ingredients, [])
        summaries = [c['pair_explanation'] for c in checks]
        self.assertEqual([s['comparison_scope'] for s in summaries], ['partial', 'unavailable', 'unavailable'])
        self.assertEqual(summaries[0]['distinct_code_pairs_compared'], 1)
        self.assertEqual(summaries[0]['same_ingredient_names'], [['공통1'], ['공통2']])
        self.assertIn('일부 성분', summaries[0]['ingredient_comparison'])
        self.assertTrue(all(c['product_pair_result'] == 'not_found' for c in checks))
        self.assertTrue(all('병용금기는 찾지 못했어요' in s['product_lookup'] for s in summaries))

    def test_same_code_only_is_not_a_distinct_ingredient_comparison(self):
        products = [dict(product_key=f'drug:{i}', product_type='drug') for i in (1, 2)]
        result = compare_gold(products, {'drug:1': [row('이름1', 'A')], 'drug:2': [row('별칭1', 'A')]}, [])[0]
        summary = result['pair_explanation']
        self.assertEqual(summary['comparison_scope'], 'no_distinct_pairs')
        self.assertEqual(summary['distinct_code_pairs_compared'], 0)
        self.assertEqual(len(summary['same_ingredient_names']), 1)

    def test_official_product_rule_survives_unavailable_ingredient_comparison(self):
        products = [dict(product_key=f'drug:{i}', product_type='drug') for i in (1, 2)]
        rule = dict(item_seq='1', mixture_item_seq='2', basis='품목 DUR', source_key='test',
                    prohbt_content='조건', remark='예외')
        check = compare_gold(products, {}, [rule])[0]
        self.assertEqual(check['pair_explanation']['comparison_scope'], 'unavailable')
        self.assertIn('금기가 확인', check['pair_explanation']['product_lookup'])
        self.assertEqual(check['rules'][0]['remark'], '예외')


class MappingReasonTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_ambiguous_and_absent_name_are_explained(self):
        repo = Repository(None, None)
        rows = [dict(item_seq='1', **row('성분A', None)),
                dict(item_seq='1', **row('성분B', None)),
                dict(item_seq='1', ingr_name=None, ingr_key='unknown', dur_ingr_code=None)]
        repo.rows = AsyncMock(side_effect=[rows, [{'ingr_name': '성분B', 'codes': ['A', 'B']}], []])
        ingredients, _ = await repo.safety(['drug:1'])
        issues = [r['mapping_issue'] for r in ingredients['drug:1']]
        self.assertIn('찾지 못함', issues[0])
        self.assertIn('여러 DUR 코드', issues[1])
        self.assertIn('성분명이 없어', issues[2])
        self.assertTrue(all(r['dur_ingr_code'] is None for r in ingredients['drug:1']))

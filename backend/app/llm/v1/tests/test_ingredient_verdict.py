import unittest
from unittest.mock import AsyncMock

from app.llm.v1.interactions import compare_gold
from app.llm.v1.repository import Repository


class IngredientVerdictTests(unittest.TestCase):
    def test_missing_mapping_does_not_erase_product_query_result(self):
        products = [{'product_key': 'drug:1', 'product_type': 'drug', 'sale_status': '판매'},
                    {'product_key': 'drug:2', 'product_type': 'drug', 'sale_status': '판매'}]
        ingredients = {'drug:1': [{'ingr_key': '생약', 'ingr_name': '생약성분', 'dur_ingr_code': None}],
                       'drug:2': [{'ingr_key': 'B', 'ingr_name': '성분B', 'dur_ingr_code': 'B'}]}
        result = compare_gold(products, ingredients, [])[0]
        self.assertEqual(result['product_pair_result'], 'not_found')
        self.assertEqual(result['ingredient_pair_result'], 'not_checkable')
        self.assertEqual(result['mapping_coverage']['drug:1']['unmapped_names'], ['생약성분'])
        self.assertEqual(result['mapping_coverage']['drug:2']['coded_count'], 1)

    def test_supplemental_codes_cross_products_without_claiming_product_dur(self):
        products = [{'product_key': f'drug:{i}', 'product_type': 'drug', 'sale_status': '판매'} for i in (1, 2)]
        ingredients = {'drug:1': [{'ingr_key': c, 'dur_ingr_code': c} for c in ['A', 'B']],
                       'drug:2': [{'ingr_key': 'C', 'dur_ingr_code': 'C'}]}
        rules = [{'ingr_code': 'A', 'mixture_ingr_code': 'B', 'item_rows': 1, 'rule_rows': 0},
                 {'ingr_code': 'B', 'mixture_ingr_code': 'C', 'item_rows': 1, 'rule_rows': 0,
                  'contents': ['원문'], 'remarks': ['제형 조건']}]
        result = compare_gold(products, ingredients, [], rules)[0]
        self.assertEqual(result['product_pair_result'], 'not_found')
        self.assertEqual(len(result['ingredient_matches']), 1)
        self.assertEqual(result['ingredient_matches'][0]['scope'], 'ingredient_only')
        self.assertEqual(result['ingredient_matches'][0]['remarks'], ['제형 조건'])


class IngredientQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_name_mapping_and_ambiguous_name(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock(side_effect=[
            [{'item_seq': '1', 'ingr_name': '성분A', 'ingr_key': 'a', 'dur_ingr_code': None},
             {'item_seq': '2', 'ingr_name': '성분B', 'ingr_key': 'b', 'dur_ingr_code': None}],
            [{'ingr_name': '성분A', 'codes': ['D1']}, {'ingr_name': '성분B', 'codes': ['D2', 'D3']}], []])
        ingredients, _ = await repo.safety(['drug:1', 'drug:2'])
        self.assertEqual(ingredients['drug:1'][0]['dur_ingr_code'], 'D1')
        self.assertIsNone(ingredients['drug:2'][0]['dur_ingr_code'])

    async def test_no_codes_skips_global_scan(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock()
        self.assertEqual(await repo.ingredient_rules({'drug:1': [{'dur_ingr_code': None}]}), [])
        repo.rows.assert_not_called()

    async def test_code_query_aggregates_conditions_and_distinct_code_pairs(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock(return_value=[])
        await repo.ingredient_rules({'drug:1': [{'dur_ingr_code': 'D1'}], 'drug:2': [{'dur_ingr_code': 'D1'}]})
        sql = repo.rows.call_args.args[0]
        self.assertIn('ingr_code < mixture_ingr_code', sql)
        self.assertIn('DISTINCT remark', sql)
        self.assertEqual(repo.rows.call_args.kwargs['codes'], ['D1'])

import unittest
from unittest.mock import AsyncMock

from app.llm.v1.interactions import compare_gold
from app.llm.v1.repository import Repository


def product(key, route='경구'):
    return dict(product_key=key, product_name=key, product_type='drug', sale_status='판매', route=route)


def ingredient(code, name):
    return dict(dur_ingr_code=code, ingr_key=name, ingr_name=name)


def group(code, **extra):
    return dict(caution_type='효능군중복', mix_type='단일', sers_name='계열A', ingr_code=code, ingr_name=code, **extra)


class NewDurTests(unittest.TestCase):
    def setUp(self):
        self.products = [product('drug:1'), product('drug:2')]
        self.ingredients = {'drug:1': [ingredient('A', '이름1')], 'drug:2': [ingredient('B', '이름2')]}

    def check(self, rules):
        return compare_gold(self.products, self.ingredients, [], dur_rules=rules)[0]

    def test_group_duplicate_is_not_contraindication(self):
        result = self.check([group('A'), group('B')])
        self.assertEqual(result['product_pair_result'], 'not_found')
        self.assertEqual(result['therapeutic_duplications'][0]['verdict'], 'duplicate_caution')
        self.assertEqual(result['therapeutic_duplications'][0]['codes'], ['A', 'B'])

    def test_group_requires_cross_product_distinct_codes_and_oral_routes(self):
        rules = [group('A'), group('B')]
        self.ingredients['drug:1'].append(ingredient('B', '이름2'))
        self.ingredients['drug:2'] = [ingredient('C', '이름3')]
        self.assertEqual(self.check(rules)['therapeutic_duplications'], [])
        self.ingredients['drug:2'] = [ingredient('B', '이름2')]
        for route in ('경구 외', None):
            self.products[1]['route'] = route
            self.assertEqual(self.check(rules)['therapeutic_duplication_result'], 'not_checkable')
        self.products[1]['route'] = '경구'
        rules[1]['mix_type'] = '복합'
        self.assertEqual(self.check(rules)['therapeutic_duplications'], [])

    def test_aliases_with_same_code_are_duplicate_ingredients_not_group_duplicates(self):
        self.ingredients['drug:2'] = [ingredient('A', '다른 이름')]
        result = self.check([group('A')])
        self.assertEqual(result['duplicate_ingredient_codes'], ['A'])
        self.assertEqual(result['therapeutic_duplications'], [])

    def test_dose_preserves_all_forms_raw_quantities_and_unknown_route(self):
        rules = [dict(caution_type='용량주의', mix_type='단일', ingr_code='A', ingr_name='성분A',
                      max_qty='성분A 1,200밀리그램', form_name=form, route=route)
                 for form, route in [('정제', '경구'), ('고형제/액제', None), ('주사', '경구 외')]]
        result = self.check(rules)
        self.assertEqual(len(result['daily_dose_limits']), 2)
        self.assertEqual(result['daily_dose_limits'][1]['max_qty'], '성분A 1,200밀리그램')
        self.assertIsNone(result['daily_dose_limits'][1]['route'])
        self.products[0]['route'] = '경구 외'
        self.assertEqual(self.check(rules)['daily_dose_limits'], [])


class NewDurQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_table_query_and_empty_codes(self):
        repo = Repository(None, None)
        repo.rows = AsyncMock(return_value=[])
        self.assertEqual(await repo.dur_ingredient_rules({}), [])
        repo.rows.assert_not_called()
        await repo.dur_ingredient_rules({'drug:1': [ingredient('A', '이름')]})
        sql = repo.rows.call_args.args[0]
        self.assertIn('gold.dur_ingredient_rule', sql)
        self.assertIn("mix_type='단일'", sql)
        self.assertIn("route IS DISTINCT FROM '경구 외'", sql)
        self.assertEqual(repo.rows.call_args.kwargs['codes'], ['A'])

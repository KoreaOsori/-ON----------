"""V1 Gold safety queries adapted to the V2 read-only Reader interface."""
from .interactions import compare_gold
from .contra_rds import RdsContraStore


class GoldSafetyRepository:
    def __init__(self, reader):
        self.reader = reader

    async def rows(self, sql, **params):
        return await self.reader.fetch(sql, params)

    async def safety(self, keys):
        ids = [k.split(':', 1)[1] for k in keys]
        ingredients = await self.rows('''SELECT item_seq,ingr_key,ingr_name,dur_ingr_code
            FROM gold.drug_ingredient WHERE item_seq=ANY(CAST(:ids AS text[])) ORDER BY item_seq,ingr_key''', ids=ids)
        missing_names = sorted({r['ingr_name'] for r in ingredients if not r['dur_ingr_code'] and r.get('ingr_name')})
        if missing_names:
            mappings = await self.rows('''SELECT ingr_name, array_agg(DISTINCT dur_ingr_code) AS codes
                FROM gold.drug_ingredient WHERE ingr_name=ANY(CAST(:names AS text[]))
                AND dur_ingr_code IS NOT NULL GROUP BY ingr_name''', names=missing_names)
            by_name = {r['ingr_name']: r['codes'] for r in mappings}
            for row in ingredients:
                codes = by_name.get(row.get('ingr_name'), [])
                if not row['dur_ingr_code'] and len(codes) == 1:
                    row['dur_ingr_code'] = codes[0]
                    row['mapping_source'] = 'gold.drug_ingredient exact unique ingredient name'
                elif not row['dur_ingr_code'] and len(codes) > 1:
                    row['mapping_issue'] = '동일 성분명에 여러 DUR 코드가 있어 자동 선택하지 않음'
            for row in ingredients:
                if not row['dur_ingr_code'] and not row.get('mapping_issue'):
                    row['mapping_issue'] = ('성분명이 없어 비교용 코드를 보완할 수 없음' if not row.get('ingr_name')
                                            else '같은 성분명으로 비교용 코드를 찾지 못함')
        else:
            for row in ingredients:
                if not row['dur_ingr_code']:
                    row['mapping_issue'] = '성분명이 없어 비교용 코드를 보완할 수 없음'
        # Product scope preserves route/form restrictions and composite-code mappings from gold.
        rules = await self.rows('''SELECT * FROM gold.drug_contraindication
            WHERE item_seq=ANY(CAST(:ids AS text[])) AND mixture_item_seq=ANY(CAST(:ids AS text[]))
            ORDER BY id''', ids=ids)
        grouped = {key: [] for key in keys}
        for row in ingredients:
            grouped[f"drug:{row['item_seq']}"].append(row)
        return grouped, rules

    async def ingredient_rules(self, ingredients):
        """Supplement product DUR with code-pair aggregation; never erase product scope."""
        codes = sorted({r['dur_ingr_code'] for rows in ingredients.values() for r in rows if r['dur_ingr_code']})
        if not codes:
            return []
        return await self.rows('''SELECT ingr_code,mixture_ingr_code,
            min(ingr_names[1]) AS ingr_name, min(mixture_ingr_names[1]) AS mixture_ingr_name,
            count(*) FILTER (WHERE basis='품목 DUR') AS item_rows,
            count(*) FILTER (WHERE basis='성분 규칙') AS rule_rows,
            array_agg(DISTINCT prohbt_content) FILTER (WHERE prohbt_content IS NOT NULL) AS contents,
            array_agg(DISTINCT remark) FILTER (WHERE remark IS NOT NULL) AS remarks
            FROM gold.drug_contraindication
            WHERE ingr_code=ANY(CAST(:codes AS text[]))
              AND mixture_ingr_code=ANY(CAST(:codes AS text[]))
              AND ingr_code <> mixture_ingr_code
            GROUP BY ingr_code,mixture_ingr_code ORDER BY ingr_code,mixture_ingr_code''', codes=codes)

    async def dur_ingredient_rules(self, ingredients):
        codes = sorted({r['dur_ingr_code'] for rows in ingredients.values() for r in rows if r['dur_ingr_code']})
        if not codes:
            return []
        # Keep original quantities and formulation/route conditions; no numeric parsing.
        return await self.rows('''SELECT caution_type,mix_type,sers_name,ingr_code,ingr_name,
            max_qty,form_name,route FROM gold.dur_ingredient_rule
            WHERE ingr_code=ANY(CAST(:codes AS text[])) AND mix_type='단일'
              AND (caution_type='효능군중복' OR
                   (caution_type='용량주의' AND route IS DISTINCT FROM '경구 외'))
            ORDER BY caution_type,sers_name,ingr_code,form_name''', codes=codes)


async def compare_products(reader, products):
    repo = GoldSafetyRepository(reader)
    drugs = [p for p in products if p['product_type'] == 'drug']
    ids = [p['product_key'].split(':', 1)[1] for p in drugs]
    rows = await repo.rows("SELECT item_seq, sale_status, route FROM gold.drug WHERE item_seq=ANY(CAST(:ids AS text[]))", ids=ids)
    metadata = {str(r['item_seq']): r for r in rows}
    enriched = [{**p, **metadata.get(p['product_key'].split(':',1)[1], {})} for p in drugs]
    ingredients, rules = await repo.safety([p['product_key'] for p in drugs])
    ingredient_rules = await repo.ingredient_rules(ingredients)
    dur_rules = await repo.dur_ingredient_rules(ingredients)
    return compare_gold(enriched, ingredients, rules, ingredient_rules, dur_rules)


class GoldContraStore(RdsContraStore):
    """V3 product comparison uses V1 Python verdicts; ingredient-name lookup stays compatible."""
    compare_products = staticmethod(compare_products)

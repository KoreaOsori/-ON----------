import json

from sqlalchemy import text


class DataUnavailable(Exception):
    pass


CATALOG = """SELECT 'drug:'||item_seq AS product_key, item_seq AS source_id,
    item_name AS product_name, entp_name AS manufacturer, 'drug' AS product_type,
    sale_status, route FROM gold.drug
    UNION ALL SELECT 'health_food:'||prdlst_report_no, prdlst_report_no,
    prdlst_nm,bssh_nm,'health_food',NULL,NULL FROM gold.health_food"""

FIELDS = {
    'drug': {'benefits': ['doc_efficacy', 'easy_efcy'], 'usage': ['doc_dosage', 'easy_use_method'],
             'precautions': ['doc_precautions', 'easy_atpn_warn', 'easy_atpn', 'easy_intrc', 'easy_se'],
             'ingredients': ['main_item_ingr'], 'storage': ['easy_deposit_method'], 'interactions': ['easy_intrc']},
    'health_food': {'benefits': ['primary_fnclty'], 'usage': ['ntk_mthd'],
                    'precautions': ['iftkn_atnt_matr_cn'], 'ingredients': ['rawmtrl_nm'],
                    'storage': ['cstdy_mthd', 'pog_daycnt']},
}


class Repository:
    """Gold retrieval within the caller's repeatable-read transaction; no vector snapshot required."""
    def __init__(self, connection, settings):
        self.conn, self.settings = connection, settings
        self.run_id = None
        self.vector_run = None
        self.vector_warning = None
        self.has_trigram = False

    async def rows(self, sql, **params):
        return [dict(r) for r in (await self.conn.execute(text(sql), params)).mappings()]

    async def start(self):
        rows = await self.rows('SELECT silver_snapshot,gold_written_at FROM gold.load_info')
        if len(rows) != 1:
            raise DataUnavailable('gold 적재 기록을 확인하세요.')
        self.run_id = f"gold:{rows[0]['silver_snapshot']}:{rows[0]['gold_written_at']}"
        self.gold_snapshot = rows[0]['silver_snapshot']

    async def prepare_vectors(self):
        available = await self.rows("""SELECT to_regclass('product_search.pipeline_config') AS config,
            to_regclass('product_search.active_snapshot') AS active,
            to_regclass('product_search.ingestion_runs') AS runs,
            to_regclass('product_search.product_links') AS links,
            to_regclass('product_search.product_vectors') AS vectors,
            EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm') AS trgm""")
        self.has_trigram = available[0]['trgm']
        if not all(available[0][key] for key in ('config', 'active', 'runs', 'links', 'vectors')):
            self.vector_warning = '벡터 DB 미준비: gold 조회만 사용했습니다.'
            return False
        config = await self.rows('SELECT * FROM product_search.pipeline_config WHERE singleton')
        if not config or (config[0]['schema_version'], config[0]['embedding_version'], config[0]['dimensions']) != (
                2, self.settings.embedding_version, self.settings.embedding_dimensions):
            self.vector_warning = '벡터 모델/차원 설정 불일치: gold 조회만 사용했습니다.'
            return False
        active = await self.rows('''SELECT r.run_id,r.snapshot FROM product_search.active_snapshot a
            JOIN product_search.ingestion_runs r USING(run_id) WHERE a.singleton AND r.status='complete' ''')
        if not active or str(active[0]['snapshot']) != str(self.gold_snapshot):
            self.vector_warning = 'gold와 벡터 snapshot 불일치 또는 미공개: gold 조회만 사용했습니다.'
            return False
        self.vector_run = active[0]['run_id']
        return True

    async def resolve(self, name):
        # No fuzzy matches or candidate selection: only one exact catalog name is accepted.
        rows = await self.rows(f'SELECT * FROM ({CATALOG}) p WHERE lower(product_name)=lower(:name) '
                               'ORDER BY product_key LIMIT 2', name=name)
        return rows, len(rows) == 1

    async def vector_documents(self, key, section, vector):
        rows = await self.rows('''WITH candidates AS MATERIALIZED (
            SELECT l.chunk_id,l.product_key,l.source_product_id,l.section_type,l.source_refs,l.snapshot,v.content,
                   v.embedding <=> CAST(:vector AS vector) AS distance
            FROM product_search.product_links l JOIN product_search.product_vectors v USING(content_hash)
            WHERE l.run_id=:run AND l.product_key=:key AND l.section_type=:section)
            SELECT * FROM candidates WHERE distance <= :threshold
            ORDER BY distance,chunk_id LIMIT :limit''', run=self.vector_run, key=key, section=section,
            vector=json.dumps(vector), threshold=self.settings.max_distance, limit=self.settings.top_k)
        return [{**r, 'source': 'product_search.product_vectors', 'vector_run_id': self.vector_run} for r in rows]

    async def documents(self, key, section, vector=None):
        kind, source_id = key.split(':', 1)
        fields = FIELDS[kind][section]
        pk = 'item_seq' if kind == 'drug' else 'prdlst_report_no'
        rows = await self.rows(f"SELECT {','.join(fields)} FROM gold.{kind} WHERE {pk}=:id", id=source_id)
        docs = []
        if rows:
            seen = set()
            for field in fields:
                value = rows[0][field]
                if value and value.strip() and value not in seen:
                    seen.add(value)
                    docs.append({'product_key': key, 'content': value, 'section_type': section,
                                 'source': f'gold.{kind}.{field}', 'source_id': source_id, 'snapshot': self.run_id})
        if kind == 'drug' and section == 'precautions':
            import json
            cautions = await self.rows('SELECT * FROM gold.drug_dur_caution WHERE item_seq=:id ORDER BY id', id=source_id)
            for row in cautions:
                docs.append({'product_key': key, 'content': json.dumps(row, ensure_ascii=False, default=str),
                             'section_type': section, 'source': 'gold.drug_dur_caution',
                             'source_id': str(row['id']), 'snapshot': self.run_id})
        return docs

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
              AND ingr_code < mixture_ingr_code
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

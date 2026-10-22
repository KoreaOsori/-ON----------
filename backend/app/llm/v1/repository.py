from sqlalchemy import text


class DataUnavailable(Exception):
    pass


CATALOG = """SELECT 'drug:'||item_seq AS product_key, item_seq AS source_id,
    item_name AS product_name, entp_name AS manufacturer, 'drug' AS product_type,
    sale_status FROM gold.drug
    UNION ALL SELECT 'health_food:'||prdlst_report_no, prdlst_report_no,
    prdlst_nm,bssh_nm,'health_food',NULL FROM gold.health_food"""

FIELDS = {
    'drug': {'benefits': ['doc_efficacy', 'easy_efcy'], 'usage': ['doc_dosage', 'easy_use_method'],
             'precautions': ['doc_precautions', 'easy_atpn_warn', 'easy_atpn', 'easy_intrc', 'easy_se'],
             'ingredients': ['main_item_ingr'], 'storage': ['easy_deposit_method']},
    'health_food': {'benefits': ['primary_fnclty'], 'usage': ['ntk_mthd'],
                    'precautions': ['iftkn_atnt_matr_cn'], 'ingredients': ['rawmtrl_nm'],
                    'storage': ['cstdy_mthd', 'pog_daycnt']},
}


class Repository:
    """Gold retrieval within the caller's repeatable-read transaction; no vector snapshot required."""
    def __init__(self, connection, settings):
        self.conn, self.settings = connection, settings
        self.run_id = None

    async def rows(self, sql, **params):
        return [dict(r) for r in (await self.conn.execute(text(sql), params)).mappings()]

    async def start(self):
        rows = await self.rows('SELECT silver_snapshot,gold_written_at FROM gold.load_info')
        if len(rows) != 1:
            raise DataUnavailable('gold 적재 기록을 확인하세요.')
        self.run_id = f"gold:{rows[0]['silver_snapshot']}:{rows[0]['gold_written_at']}"

    async def resolve(self, name, selected_key=None):
        if selected_key:
            rows = await self.rows(f'SELECT * FROM ({CATALOG}) p WHERE product_key=:key', key=selected_key)
            return rows, bool(rows)
        rows = await self.rows(f'SELECT * FROM ({CATALOG}) p WHERE lower(product_name)=lower(:name) '
                               'ORDER BY product_key LIMIT 11', name=name)
        if rows:
            return rows[:10], len(rows) == 1
        escaped = name.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        rows = await self.rows(f'SELECT * FROM ({CATALOG}) p WHERE lower(product_name) LIKE :pattern '
                               'ORDER BY product_key LIMIT 10', pattern=f'%{escaped}%')
        return rows, False

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
        # Product scope preserves route/form restrictions and composite-code mappings from gold.
        rules = await self.rows('''SELECT * FROM gold.drug_contraindication
            WHERE item_seq=ANY(CAST(:ids AS text[])) AND mixture_item_seq=ANY(CAST(:ids AS text[]))
            ORDER BY id''', ids=ids)
        grouped = {key: [] for key in keys}
        for row in ingredients:
            grouped[f"drug:{row['item_seq']}"].append(row)
        return grouped, rules

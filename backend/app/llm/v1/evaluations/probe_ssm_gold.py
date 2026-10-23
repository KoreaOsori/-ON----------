"""Read-only Gold diagnostic through an already-open local SSM tunnel.

Credentials stay in memory. TLS verifies the RDS hostname, while hostaddr uses
the tunnel. This script never starts an EC2 command or changes database rows.
"""
import argparse
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.llm.v1.config import Settings
from app.llm.v1.database import CA_FILE, RDS, read_credentials
from app.llm.v1.interactions import compare_gold
from app.llm.v1.repository import Repository


class TunnelRepository(Repository):
    async def rows(self, query, **params):
        query = re.sub(r'(?<!:):(\w+)', r'%(\1)s', query)
        return self.conn.execute(query, params).fetchall()


async def inspect(conn, names):
    repo = TunnelRepository(conn, Settings(_env_file=None, auth_mode='default_chain'))
    await repo.start()
    products, unresolved = [], []
    for name in names:
        found, confirmed = await repo.resolve(name)
        if confirmed:
            products.extend(found)
        else:
            unresolved.append(name)
    keys = [p['product_key'] for p in products if p['product_type'] == 'drug']
    ingredients, rules = await repo.safety(keys)
    aggregate = await repo.ingredient_rules(ingredients)
    dur = await repo.dur_ingredient_rules(ingredients)
    schema = conn.execute("""SELECT table_name,column_name,data_type
        FROM information_schema.columns WHERE table_schema='gold' AND table_name IN
        ('drug','drug_ingredient','drug_contraindication','dur_ingredient_rule','health_food')
        ORDER BY table_name,ordinal_position""").fetchall()
    active = conn.execute('''SELECT r.run_id,r.snapshot,r.status FROM product_search.active_snapshot a
        JOIN product_search.ingestion_runs r USING(run_id) WHERE a.singleton''').fetchall()
    evidence = []
    for key in keys:
        evidence.extend({'product_key': key, 'text': d['content']} for d in await repo.documents(key, 'interactions'))
    missing_names = sorted({r['ingr_name'] for rows in ingredients.values() for r in rows
                            if not r['dur_ingr_code'] and r.get('ingr_name')})
    candidates = conn.execute('''SELECT DISTINCT ingr_name,ingr_code,mix_type,caution_type
        FROM gold.dur_ingredient_rule WHERE ingr_name=ANY(%s)''', (missing_names,)).fetchall()
    return dict(products=products, unresolved=unresolved, ingredients=ingredients,
                checks=compare_gold(products, ingredients, rules, aggregate, dur),
                vector_ready=await repo.prepare_vectors(), vector_warning=repo.vector_warning,
                schema=schema, gold_run=repo.run_id, vector_active=active, evidence=evidence,
                missing_code_rule_candidates=candidates)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5432)
    parser.add_argument('--products', nargs='+', default=['코푸시럽', '셉트린정', '코데농정'])
    args = parser.parse_args()
    settings = Settings(_env_file=None, auth_mode='default_chain')
    user, password, host = read_credentials(settings)
    with psycopg.connect(host=host, hostaddr='127.0.0.1', port=args.port,
                         dbname=RDS.database, user=user, password=password,
                         sslmode='verify-full', sslrootcert=str(CA_FILE), connect_timeout=15,
                         options='-c default_transaction_read_only=on -c statement_timeout=15000',
                         row_factory=dict_row) as conn:
        result = asyncio.run(inspect(conn, args.products))
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S')
    target = Path(__file__).with_name(f'gold_probe_{stamp}.json')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(f'Read-only diagnostic saved: {target}')
    for product in result['products']:
        rows = result['ingredients'].get(product['product_key'], [])
        print(json.dumps(dict(product=product['product_name'], ingredients=rows), ensure_ascii=True))


if __name__ == '__main__':
    main()

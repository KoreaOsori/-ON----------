import json
import os
from itertools import islice
from pathlib import Path

from build_documents import digest
from bundle import batched, records, verify_files
from cache import EmbeddingCache

LOCK_ID = 842701
LINK_FIELDS = ("chunk_id", "content_hash", "product_type", "source_product_id", "product_key",
               "product_name", "manufacturer", "section_type", "source_refs", "metadata",
               "chunk_index", "document_version", "source_s3_key", "snapshot", "sale_status")


def connect():
    import psycopg
    from aws_runtime import database_options
    return psycopg.connect(**database_options(), connect_timeout=15, autocommit=True)


def check_config(conn, config):
    found = conn.execute("SELECT schema_version,embedding_version,dimensions FROM product_search.pipeline_config WHERE singleton").fetchone()
    if found != (2, config.version, config.dimensions):
        raise ValueError("DB schema 또는 임베딩 모델/차원 불일치. 기존 DB를 자동 변경하지 않습니다.")


def lock(conn):
    if not conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
        raise RuntimeError("다른 적재/인덱스 작업이 실행 중입니다.")


def init_db(config):
    with connect() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        if conn.execute("SELECT to_regclass('product_search.index_config')").fetchone()[0]:
            raise ValueError("v1 스키마가 있습니다. 별도 DB/스키마로 재구축하는 수동 전환이 필요합니다.")
        sql = (Path(__file__).parent / "sql/init.sql").read_text(encoding="utf-8")
        conn.execute(sql.replace("__DIMENSIONS__", str(config.dimensions)))
        conn.execute("INSERT INTO product_search.pipeline_config VALUES(true,2,%s,%s) ON CONFLICT DO NOTHING",
                     (config.version, config.dimensions))
        check_config(conn, config)


def create_index(config):
    with connect() as conn:
        lock(conn)
        check_config(conn, config)
        validity = conn.execute("SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('product_search.product_vectors_embedding_idx')").fetchone()
        if validity and not validity[0]:
            # A failed concurrent build may leave an invalid index; never silently accept it.
            raise RuntimeError("이전 인덱스 생성이 실패한 상태입니다. DBA가 invalid index를 정리한 뒤 다시 실행하세요.")
        conn.execute((Path(__file__).parent / "sql/create_index.sql").read_text(encoding="utf-8"))


def run_identity(manifest, config):
    return digest(json.dumps({"manifest": manifest, "embedding_version": config.version}, sort_keys=True))


def write_vectors(conn, batch, vectors, run_id, offset):
    """Only one bounded batch is duplicated; checkpoint commits with its data."""
    with conn.transaction():
        conn.execute("CREATE TEMP TABLE vector_batch (LIKE product_search.product_vectors INCLUDING DEFAULTS) ON COMMIT DROP")
        with conn.cursor().copy("COPY vector_batch(content_hash,product_type,section_type,content,embedding) FROM STDIN") as copy:
            for d in batch:
                copy.write_row((d["content_hash"], d["product_type"], d["section_type"], d["content"],
                                json.dumps(vectors[d["content_hash"]])))
        conn.execute("INSERT INTO product_search.product_vectors SELECT * FROM vector_batch WHERE true ON CONFLICT(content_hash) DO NOTHING")
        conn.execute("UPDATE product_search.ingestion_runs SET documents_loaded=%s,updated_at=now() WHERE run_id=%s",
                     (offset, run_id))


def write_links(conn, batch, run_id, offset):
    from psycopg.types.json import Jsonb
    with conn.transaction():
        with conn.cursor().copy("COPY product_search.product_links(run_id," + ",".join(LINK_FIELDS) + ") FROM STDIN") as copy:
            for c in batch:
                copy.write_row((run_id, *(Jsonb(c[k]) if k in ("source_refs", "metadata") else c.get(k) for k in LINK_FIELDS)))
        conn.execute("UPDATE product_search.ingestion_runs SET links_loaded=%s,updated_at=now() WHERE run_id=%s", (offset, run_id))


def publish_run(conn, run_id, manifest, rollback=False, reason="publish completed snapshot"):
    if not manifest["complete"]:
        raise ValueError("샘플 bundle은 공개할 수 없습니다. 전체 prepare 결과가 필요합니다.")
    with conn.transaction():
        row = conn.execute("SELECT status,documents_loaded,links_loaded FROM product_search.ingestion_runs WHERE run_id=%s", (run_id,)).fetchone()
        if row != ("complete", manifest["documents"], manifest["links"]):
            raise ValueError("완료되지 않은 run은 공개할 수 없습니다.")
        latest = conn.execute("SELECT r.snapshot FROM product_search.active_snapshot a JOIN product_search.ingestion_runs r USING(run_id)").fetchone()
        if latest and str(latest[0]) > manifest["snapshot"] and not rollback:
            raise ValueError("현재 공개된 데이터보다 오래된 스냅샷입니다.")
        conn.execute("INSERT INTO product_search.publication_events(from_run_id,to_run_id,operation,reason) "
                     "VALUES((SELECT run_id FROM product_search.active_snapshot WHERE singleton),%s,%s,%s)",
                     (run_id, "rollback" if rollback else "publish", reason))
        conn.execute("INSERT INTO product_search.active_snapshot VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET run_id=EXCLUDED.run_id", (run_id,))


def ingest(root, manifest, config, cache_path, batch_size=128, publish=False):
    from psycopg.types.json import Jsonb
    if publish and not manifest["complete"]:
        raise ValueError("샘플 bundle 공개는 허용하지 않습니다.")
    run_id = run_identity(manifest, config)
    with connect() as conn, EmbeddingCache(cache_path, config) as cache:
        lock(conn)
        check_config(conn, config)
        conn.execute("INSERT INTO product_search.ingestion_runs(run_id,snapshot,manifest,status) VALUES(%s,%s,%s,'loading') ON CONFLICT DO NOTHING",
                     (run_id, manifest["snapshot"], Jsonb(manifest)))
        status, docs_done, links_done = conn.execute("SELECT status,documents_loaded,links_loaded FROM product_search.ingestion_runs WHERE run_id=%s", (run_id,)).fetchone()
        if status == "pruning":
            raise ValueError("정리 중인 run입니다. prune을 완료한 뒤 다시 적재하세요.")
        if status != "complete":
            for batch in batched(islice(records(root / "documents.jsonl"), docs_done, None), batch_size):
                hashes = [d["content_hash"] for d in batch]
                existing = {r[0] for r in conn.execute("SELECT content_hash FROM product_search.product_vectors WHERE content_hash=ANY(%s)", (hashes,))}
                missing = [d for d in batch if d["content_hash"] not in existing]
                vectors = cache.get_many([d["content_hash"] for d in missing])
                if len(vectors) != len(missing):
                    raise ValueError("임베딩 캐시가 부족합니다. embed 명령을 먼저 실행하세요.")
                docs_done += len(batch)
                write_vectors(conn, missing, vectors, run_id, docs_done)
            for batch in batched(islice(records(root / "links.jsonl"), links_done, None), batch_size):
                links_done += len(batch)
                write_links(conn, batch, run_id, links_done)
                if links_done % (batch_size * 10) == 0:
                    print(f"RDS links checkpoint: {links_done:,}", flush=True)
            verify_files(root, manifest)
            actual = conn.execute("SELECT count(*) FROM product_search.product_links WHERE run_id=%s", (run_id,)).fetchone()[0]
            if docs_done != manifest["documents"] or links_done != manifest["links"] or actual != manifest["links"]:
                raise ValueError("적재 완료 건수 불일치")
            conn.execute("UPDATE product_search.ingestion_runs SET status='complete',updated_at=now() WHERE run_id=%s", (run_id,))
        if publish:
            publish_run(conn, run_id, manifest)
    return {"run_id": run_id, "documents_loaded": docs_done, "links_loaded": links_done, "published": publish}

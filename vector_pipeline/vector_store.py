import hashlib
import json
import os
import uuid
from pathlib import Path

from embedding import validate_vector

FIELDS = ("chunk_id", "product_type", "source_product_id", "product_key", "section_type",
          "source_ref", "chunk_index", "content", "content_hash", "document_version",
          "source_s3_key", "snapshot", "sale_status")


def connect():
    import psycopg
    # libpq reads PGHOST/PGUSER/PGPASSWORD/PGSSLROOTCERT without logging secrets.
    if not all(os.getenv(x) for x in ("PGHOST", "PGDATABASE", "PGUSER")):
        raise ValueError("PGHOST, PGDATABASE, PGUSER 설정이 필요합니다.")
    return psycopg.connect(sslmode=os.getenv("PGSSLMODE", "verify-full"),
                           connect_timeout=15, autocommit=True)


def check_config(conn, config):
    found = conn.execute("SELECT embedding_version, dimensions FROM product_search.index_config WHERE singleton").fetchone()
    if found != (config.version, config.dimensions):
        raise ValueError("DB와 임베딩 모델/차원이 다릅니다. 기존 인덱스에 혼합할 수 없습니다.")


def init_db(config):
    with connect() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(842701)")
        sql = (Path(__file__).parent / "sql/init.sql").read_text(encoding="utf-8")
        conn.execute(sql.replace("__DIMENSIONS__", str(config.dimensions)))
        conn.execute("INSERT INTO product_search.index_config VALUES (true, %s, %s) ON CONFLICT DO NOTHING",
                     (config.version, config.dimensions))
        check_config(conn, config)


def ingest(path, manifest, config, embedder, replace_snapshot=False):
    from psycopg.types.json import Jsonb
    if replace_snapshot and not manifest["complete"]:
        raise ValueError("일부 샘플로 전체 스냅샷을 교체할 수 없습니다.")
    embedded = reused = total = 0
    with connect() as conn:
        # Session lock covers embedding + final publish; concurrent loaders fail early.
        if not conn.execute("SELECT pg_try_advisory_lock(842701)").fetchone()[0]:
            raise RuntimeError("다른 벡터 적재 작업이 실행 중입니다.")
        check_config(conn, config)
        latest = conn.execute("SELECT max(snapshot) FROM product_search.product_vectors").fetchone()[0]
        if latest and str(latest) > manifest["snapshot"]:
            raise ValueError("현재 데이터보다 오래된 스냅샷은 적재할 수 없습니다.")
        conn.execute("CREATE TEMP TABLE incoming (LIKE product_search.product_vectors INCLUDING DEFAULTS) ON COMMIT PRESERVE ROWS")
        conn.execute("CREATE UNIQUE INDEX ON incoming(chunk_id)")
        conn.execute("CREATE INDEX ON incoming(content_hash, embedding_version)")
        columns = ",".join(FIELDS) + ",embedding_version,embedding"
        placeholders = ",".join(["%s"] * (len(FIELDS) + 1)) + ",%s::vector"
        input_hash = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for line in stream:
                input_hash.update(line)
                chunk = json.loads(line)
                cached = conn.execute(
                    "SELECT embedding::text FROM product_search.product_vectors WHERE content_hash=%s AND embedding_version=%s "
                    "UNION ALL SELECT embedding::text FROM incoming WHERE content_hash=%s AND embedding_version=%s LIMIT 1",
                    (chunk["content_hash"], config.version) * 2).fetchone()
                if cached:
                    vector_text = cached[0]
                    reused += 1
                else:
                    vector = embedder.embed(chunk["content"])
                    validate_vector(vector, config.dimensions)
                    vector_text = json.dumps(vector)
                    embedded += 1
                conn.execute(f"INSERT INTO incoming ({columns}) VALUES ({placeholders})",
                             tuple(chunk.get(f) for f in FIELDS) + (config.version, vector_text))
                total += 1
                if total % 1000 == 0:
                    print(json.dumps({"staged": total, "embedded": embedded, "reused": reused}), flush=True)
        if total != manifest["chunks"] or input_hash.hexdigest() != manifest["sha256"]:
            raise ValueError("적재 건수 또는 파일 해시가 manifest와 다릅니다.")
        with conn.transaction():
            assignments = ",".join(f"{f}=EXCLUDED.{f}" for f in (*FIELDS[1:], "embedding_version", "embedding"))
            conn.execute(f"INSERT INTO product_search.product_vectors ({columns}) SELECT {columns} FROM incoming WHERE true "
                         f"ON CONFLICT(chunk_id) DO UPDATE SET {assignments}, updated_at=now()")
            if replace_snapshot:
                # Explicit full snapshot publish: remove chunks absent from BOTH validated sources.
                conn.execute("DELETE FROM product_search.product_vectors p WHERE NOT EXISTS "
                             "(SELECT 1 FROM incoming i WHERE i.chunk_id=p.chunk_id)")
            else:
                # Refresh whole products included in this run, without deleting absent products.
                conn.execute("DELETE FROM product_search.product_vectors p WHERE EXISTS "
                             "(SELECT 1 FROM incoming i WHERE i.product_key=p.product_key) AND NOT EXISTS "
                             "(SELECT 1 FROM incoming i WHERE i.chunk_id=p.chunk_id)")
            conn.execute("INSERT INTO product_search.ingestion_runs(run_id,snapshot,chunks,manifest) VALUES(%s,%s,%s,%s)",
                         (uuid.uuid4(), manifest["snapshot"], total, Jsonb(manifest)))
        return {"chunks": total, "embedded": embedded, "reused": reused}

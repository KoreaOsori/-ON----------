"""S3 Gold → RDS 적재 (gold 파일은 build.py 가 만든다. 테이블 정의: schema.sql).

s3://{버킷}/gold/_latest.json 의 gold 파일을 임시 폴더로 받아, 트랜잭션 하나 안에서 gold 스키마를 지우고 다시 채운다.
하나라도 실패하면 전부 되돌려 기존 gold 가 그대로 남는다. 검증: DB 제약(PK, FK, CHECK) + 테이블별 행 수 = gold 파일 행 수.

  python pipeline/gold/load.py --host localhost             # SSM 터널로 RDS 에 적재 (접속 정보: Secrets Manager)
  python pipeline/gold/load.py                              # EC2 에서 RDS 에 직접 적재
  python pipeline/gold/load.py --dsn postgresql://...       # 다른 DB (로컬 테스트 등)
  python pipeline/gold/load.py --force                      # 이미 적재한 gold 여도 다시 적재 (스키마를 바꿨을 때)

이미 적재한 gold(gold/_latest.json 의 written_at 이 gold.load_info 와 같음)면 아무것도 하지 않고 끝난다.
종료 코드: 0 = 적재 또는 건너뜀, 1 = 실패 (기존 gold 유지), 2 = DB 접속 실패 (RDS 가 꺼져 있거나 터널·접속 정보 확인)

RDS 접속 정보는 Secrets Manager `pill-check/dev/app` 의 DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD.
"""

import argparse
import io
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build import TABLE_COLUMNS, TABLES  # noqa: E402
from s3store import DEFAULT_BUCKET, Store  # noqa: E402

SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
APP_SECRET = "pill-check/dev/app"
REGION = "us-east-1"
CONNECT_TIMEOUT_SECONDS = 15
COPY_BATCH_ROWS = 5000  # gold 파일을 CSV 로 바꿔 보내는 단위 (drug 는 허가 문서 글이 길어 작게)


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def pg_text_array(column):
    """list<string> 열 → PostgreSQL 배열 리터럴 문자열 열 ('{"a","b"}'). null 목록은 null."""
    lists = column.combine_chunks() if isinstance(column, pa.ChunkedArray) else column
    escaped = pc.replace_substring(pc.replace_substring(lists.values, "\\", "\\\\"), '"', '\\"')
    quoted = pc.binary_join_element_wise('"', escaped, '"', "")
    joined = pc.binary_join(pa.ListArray.from_arrays(lists.offsets, quoted, mask=lists.is_null()), ",")
    return pc.binary_join_element_wise("{", joined, "}", "")


def copy_parquet(cur, table, path):
    """gold 파일을 CSV 로 바꿔 COPY. null 은 따옴표 없는 빈 값 = NULL, 빈 문자열은 "" 로 구분된다."""
    columns = TABLE_COLUMNS[table]
    names = [name for name, _ in columns]
    options = pacsv.WriteOptions(include_header=False)
    count = 0
    with cur.copy(f"COPY gold.{table} ({', '.join(names)}) FROM STDIN WITH (FORMAT csv)") as copy:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=COPY_BATCH_ROWS, columns=names):
            arrays = [pg_text_array(batch.column(name)) if type_ == "text[]" else batch.column(name)
                      for name, type_ in columns]
            buffer = io.BytesIO()
            pacsv.write_csv(pa.RecordBatch.from_arrays(arrays, names=names), buffer, write_options=options)
            copy.write(buffer.getvalue())
            count += batch.num_rows
    return count


def connection_info(host_override):
    import boto3

    secret = json.loads(boto3.client("secretsmanager", region_name=REGION)
                        .get_secret_value(SecretId=APP_SECRET)["SecretString"])
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USERNAME", "DB_PASSWORD") if not secret.get(k)]
    if missing:
        sys.exit(f"Secrets Manager {APP_SECRET} 에 값이 없음: {missing}")
    return {
        "host": host_override or secret["DB_HOST"], "port": int(secret.get("DB_PORT") or 5432),
        "dbname": secret["DB_NAME"], "user": secret["DB_USERNAME"], "password": secret["DB_PASSWORD"],
        "sslmode": "require",
    }


def loaded_gold(cur):
    """RDS 에 마지막으로 적재한 gold 의 written_at. gold 가 없거나 예전 구조면 None."""
    cur.execute("SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'gold' AND table_name = 'load_info' AND column_name = 'gold_written_at'")
    if cur.fetchone() is None:
        return None
    cur.execute("SELECT gold_written_at FROM gold.load_info")
    row = cur.fetchone()
    return row[0] if row else None


def load(conn, store, root, force=False):
    """S3 gold 를 RDS 에 다시 채운다. 이미 적재한 gold 면 None, 적재했으면 테이블별 행 수를 돌려준다."""
    latest = store.get_json("gold/_latest.json")
    if latest is None:
        raise RuntimeError(f"s3://{store.bucket}/gold/_latest.json 없음 — gold/build.py 를 먼저 실행할 것")
    log(f"gold snapshot={latest['snapshot']} (작성 {latest['written_at']}, silver 작성 {latest['silver_written_at']})")
    with conn.cursor() as cur:
        previous = loaded_gold(cur)
    conn.commit()
    if previous == latest["written_at"] and not force:
        log("이미 적재한 gold 라 건너뜀 (다시 적재하려면 --force)")
        return None

    paths = {}
    for table in TABLES:
        prefix = f"gold/{table}/snapshot={latest['snapshot']}/"
        store.download_prefix(prefix, Path(root) / prefix)
        paths[table] = Path(root) / prefix / "data.parquet"
    schema_sql, index_sql = SCHEMA_SQL.read_text(encoding="utf-8").split("-- INDEXES")

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(schema_sql)
        written = {}
        for table in TABLES:
            written[table] = copy_parquet(cur, table, paths[table])
            log(f"  {table} {written[table]:,}행")
        cur.execute(index_sql)
        counts = {}
        for table in TABLES:
            cur.execute(f"SELECT count(*) FROM gold.{table}")
            counts[table] = cur.fetchone()[0]
        problems = [f"{t}: DB {counts[t]:,}행 != gold 파일 {latest['row_counts'][t]:,}행"
                    for t in TABLES if counts[t] != latest["row_counts"][t] or written[t] != counts[t]]
        if problems:
            raise RuntimeError("적재 후 확인 실패 (모두 되돌림): " + "; ".join(problems))
        cur.execute("INSERT INTO gold.load_info (silver_snapshot, silver_written_at, gold_written_at, spec_version, "
                    "row_counts, carried_over, excluded) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (latest["snapshot"], latest["silver_written_at"], latest["written_at"], latest["spec_version"],
                     json.dumps(counts), json.dumps(latest["carried_over"]), json.dumps(latest["excluded"])))
    return counts


def main():
    parser = argparse.ArgumentParser(description="S3 gold → RDS 적재")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--host", help="DB 호스트 덮어쓰기 (SSM 터널이면 localhost)")
    parser.add_argument("--dsn", help="Secrets Manager 대신 이 접속 문자열 사용")
    parser.add_argument("--force", action="store_true", help="이미 적재한 gold 여도 다시 적재")
    args = parser.parse_args()

    import psycopg

    conninfo = args.dsn or connection_info(args.host)
    try:
        # 꺼진 RDS 는 기다려도 응답이 없으므로 빨리 실패한다 (제한이 없으면 4분 넘게 기다림)
        conn = (psycopg.connect(conninfo, connect_timeout=CONNECT_TIMEOUT_SECONDS) if isinstance(conninfo, str)
                else psycopg.connect(**conninfo, connect_timeout=CONNECT_TIMEOUT_SECONDS))
    except psycopg.OperationalError as error:
        log(f"DB 접속 실패 — RDS 가 꺼져 있거나, SSM 터널(--host localhost)·접속 정보를 확인할 것: {error}")
        sys.exit(2)
    root = Path(tempfile.mkdtemp(prefix="pill-gold-load-"))
    try:
        with conn:
            log("적재 시작 (실패하면 기존 gold 유지)")
            counts = load(conn, Store(args.bucket), root, args.force)
    except RuntimeError as error:
        log(str(error))
        sys.exit(1)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if counts is not None:
        log(f"완료 {counts}")


if __name__ == "__main__":
    main()

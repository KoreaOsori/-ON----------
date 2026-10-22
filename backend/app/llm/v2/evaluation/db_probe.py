"""대상 DB 점검: v2 가 기대하는 스키마가 있는지, 검색 쿼리가 실제로 도는지 읽기 전용으로 확인한다.

    python -m app.llm.v2.evaluation.db_probe [--name 아로나민골드정]

- 모두 SELECT 뿐이다(연결 자체가 default_transaction_read_only=on). 제품 본문·비밀번호는 출력하지 않는다.
- 평소 v2 는 오류의 클래스 이름만 남기지만(비밀 노출 방지), 이 도구는 원인을 찾기 위해 DB 오류 메시지를 그대로 보여 준다.
  메시지에는 SQL 문과 바인딩된 값(run_id, 입력한 제품명)이 들어갈 수 있다. 비밀번호는 들어가지 않는다.
"""
import argparse
import asyncio

from app.llm.v2.config import V2Settings
from app.llm.v2.db import build_engine, open_connection, reader_factory_for
from app.llm.v2.search import active_run_id, check_config, find_products

CATALOG_QUERIES = (
    ("스키마", "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg\\_%' AND schema_name <> 'information_schema' ORDER BY 1"),
    ("product_search 테이블", "SELECT table_name FROM information_schema.tables WHERE table_schema = 'product_search' ORDER BY 1"),
    ("확장(extension)", "SELECT e.extname || ' (' || n.nspname || ')' AS ext FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace ORDER BY 1"),
    ("product_links 컬럼", "SELECT column_name FROM information_schema.columns WHERE table_schema = 'product_search' AND table_name = 'product_links' ORDER BY ordinal_position"),
    ("product_vectors 컬럼", "SELECT column_name || ' ' || udt_name AS col FROM information_schema.columns WHERE table_schema = 'product_search' AND table_name = 'product_vectors' ORDER BY ordinal_position"),
    ("pipeline_config", "SELECT schema_version, embedding_version, dimensions FROM product_search.pipeline_config"),
    ("active_snapshot", "SELECT run_id FROM product_search.active_snapshot"),
)


def short(exc: BaseException, lines: int = 6) -> str:
    return f"{type(exc).__name__}: " + " / ".join(str(exc).strip().splitlines()[:lines])


async def catalog(settings: V2Settings) -> None:
    print("== 1. 직접 조회 (asyncpg) ==")
    connection = await open_connection(settings)
    try:
        for title, sql in CATALOG_QUERIES:
            try:
                rows = await connection.fetch(sql)
                print(f"- {title}: " + (", ".join(" | ".join(str(v) for v in r.values()) for r in rows) or "(없음)"))
            except Exception as exc:  # noqa: BLE001
                print(f"- {title}: 실패 → {short(exc)}")
    finally:
        await connection.close()


async def through_reader(settings: V2Settings, name: str) -> None:
    print("\n== 2. v2 가 쓰는 방식 (SQLAlchemy + 읽기 전용 트랜잭션) ==")
    engine = build_engine(settings)
    open_reader = reader_factory_for(engine)
    try:
        async with open_reader() as reader:
            for title, call in (
                ("check_config", lambda: check_config(reader, settings)),
                ("active_run_id", lambda: active_run_id(reader)),
            ):
                try:
                    print(f"- {title}: 성공 → {await call()}")
                except Exception as exc:  # noqa: BLE001
                    print(f"- {title}: 실패 → {short(exc)}")
                    return
            run_id = await active_run_id(reader)
            try:
                found = await find_products(reader, run_id, name)
                names = [p["product_name"] for p in found["products"]]
                print(f"- find_products({name!r}): 성공 → mode={found['mode']} 후보 {len(names)}개 {names[:5]}")
            except Exception as exc:  # noqa: BLE001
                print(f"- find_products({name!r}): 실패 → {short(exc, 10)}")
    except Exception as exc:  # noqa: BLE001
        print(f"- 트랜잭션 시작 실패 → {short(exc, 10)}")
    finally:
        await engine.dispose()


async def main(args: argparse.Namespace) -> None:
    settings = V2Settings.from_env()
    print(f"DB={settings.db_host}:{settings.db_port}/{settings.db_name} user={settings.db_user} ssl={settings.db_ssl_mode}\n")
    await catalog(settings)
    await through_reader(settings, args.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="대상 DB 점검(읽기 전용)")
    parser.add_argument("--name", default="아로나민골드정", help="제품명 조회를 시험할 이름")
    asyncio.run(main(parser.parse_args()))

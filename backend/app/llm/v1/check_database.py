"""Read-only connectivity check. Does not print credentials or create tables."""
import asyncio
import json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .database import DatabaseConnectionError, create_database_engine


async def check():
    engine = create_database_engine(Settings())
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                database = (await conn.execute(text("SELECT current_database()"))).scalar_one()
                return {"connected": True, "database": database}
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(check()), ensure_ascii=False))
    except (DatabaseConnectionError, SQLAlchemyError, OSError):
        print("DB 연결 실패: IAM/Secrets Manager, RDS 네트워크, TLS 및 DB 권한을 확인하세요.")
        raise SystemExit(1) from None

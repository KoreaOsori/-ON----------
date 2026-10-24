import os

# 테스트는 외부 서비스(Bedrock 등)를 호출하지 않는 목업 설정으로 실행한다
os.environ.update(
    {
        "APP_ENV": "test",
        "BEDROCK_ENABLED": "false",
        "DRUG_DATA_SOURCE": "mock",
        "OCR_PROVIDER": "mock",
        "GUEST_DAILY_QUESTION_LIMIT": "2",
    }
)

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.modules.chat.rate_limit import GuestQuota  # noqa: E402
from app.modules.chat.router import get_guest_quota  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def decr(self, key):
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    async def expire(self, key, seconds):
        return True


@pytest.fixture
async def client():
    quota = GuestQuota(FakeRedis())  # type: ignore[arg-type]
    app.dependency_overrides[get_guest_quota] = lambda: quota
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture
async def db_client(client):
    """회원·복용약 API 용: SQLite 메모리 DB 로 get_db 를 바꾼다 (운영은 PostgreSQL)"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.db.session import get_db

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield client
    await engine.dispose()

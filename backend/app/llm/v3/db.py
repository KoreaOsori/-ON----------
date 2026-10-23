"""v2 검색용 읽기 전용 DB 연결.

안전장치(합의 사항)
1. 읽기 전용: 연결 시작 파라미터로 default_transaction_read_only=on 을 건다.
   계정 권한이 강해도(마스터 계정) 쓰기 SQL 은 DB 가 거부한다. 검색 트랜잭션에는 추가로
   REPEATABLE READ READ ONLY 를 명시한다(vector_pipeline/search.py 와 동일).
2. 파라미터 바인딩만 사용: 이 모듈의 Reader.fetch 는 (sql, params) 를 분리해서 받는다.
3. 비밀값 비노출: 비밀번호는 로그/예외/응답에 넣지 않는다. 예외는 클래스 이름만 남기고 원인 체인은 끊는다.
4. 마스터 시크릿 회전 대응: RDS_SECRET_ARN 이 있으면 "새 연결을 만들 때마다" Secrets Manager 에서 읽는다.
   시작 시 한 번 읽어 URL/풀에 고정하지 않는다. 인증 실패가 나면 다시 읽어서 한 번 더 시도한다.

SQLAlchemy/asyncpg/boto3 는 함수 안에서 import 한다(설치 없이도 이 모듈의 나머지를 테스트할 수 있게).
"""
import asyncio
import json
import logging
import ssl
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Mapping, Protocol

from app.llm.v3.config import ConfigError, V3Settings

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(Exception):
    """DB 연결/인증 실패. 메시지에는 비밀값·호스트 정보를 넣지 않는다."""


class Reader(Protocol):
    """검색 모듈이 보는 DB 인터페이스. SQL 과 파라미터를 따로 받는다(문자열 결합 금지)."""

    async def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]: ...


# 새 읽기 전용 트랜잭션을 여는 팩토리. 도구/평가 코드는 이것만 받는다 → 테스트에서 가짜로 교체.
ReaderFactory = Callable[[], "AsyncContextManagerLike"]


class AsyncContextManagerLike(Protocol):
    async def __aenter__(self) -> Reader: ...
    async def __aexit__(self, *exc: object) -> None: ...


def safe_error_name(exc: BaseException) -> str:
    """로그/응답용 오류 표기. 메시지(str(exc))는 호스트·사용자명이 섞일 수 있어 쓰지 않는다."""
    sqlstate = getattr(exc, "sqlstate", None)
    name = type(exc).__name__
    return f"{name}({sqlstate})" if sqlstate else name


# --------------------------------------------------------------------------- 자격증명

def resolve_credentials(settings: V3Settings, secret_client: Any = None) -> tuple[str, str | None]:
    """(user, password) 를 반환한다. RDS_SECRET_ARN 이 있으면 호출할 때마다 시크릿을 읽는다."""
    if settings.rds_secret_arn:
        try:
            if secret_client is None:
                import boto3

                secret_client = boto3.client("secretsmanager", region_name=settings.region)
            response = secret_client.get_secret_value(SecretId=settings.rds_secret_arn)
            secret = json.loads(response["SecretString"])
            user, password = secret["username"], secret["password"]
            if not isinstance(user, str) or not isinstance(password, str) or not user:
                raise ValueError
            return user, password
        except Exception as exc:  # noqa: BLE001 - 원인 메시지에 비밀값이 섞일 수 있어 이름만 남긴다.
            raise DatabaseUnavailableError(f"DB 시크릿을 읽지 못했습니다({type(exc).__name__}).") from None
    if not settings.db_user:
        raise ConfigError("DB 사용자 설정이 필요합니다. PGUSER 또는 RDS_SECRET_ARN 을 확인하세요.")
    return settings.db_user, settings.db_password


_ENDPOINT_CACHE: dict[str, tuple[str, int, str]] = {}


def resolve_endpoint(settings: V3Settings, secret_client: Any = None) -> tuple[str, int, str]:
    """(host, port, database). 환경변수로 준 값이 우선이고, 없는 값은 앱 시크릿의 DB_HOST, DB_PORT, DB_NAME 에서 읽는다.

    호스트·포트·DB 이름은 바뀌지 않아 프로세스 안에서 한 번만 읽어 둔다(계정은 회전하므로 resolve_credentials 가 매번 읽는다).
    오류 메시지에는 시크릿 이름·값을 넣지 않는다."""
    if settings.db_host and settings.db_name:
        return settings.db_host, settings.db_port or 5432, settings.db_name
    secret_id = settings.app_secret_id
    if not secret_id:
        raise ConfigError("DB host/name 설정이 필요합니다. PGHOST, PGDATABASE 를 확인하세요.")
    if secret_id not in _ENDPOINT_CACHE:
        try:
            if secret_client is None:
                import boto3

                secret_client = boto3.client("secretsmanager", region_name=settings.region)
            secret = json.loads(secret_client.get_secret_value(SecretId=secret_id)["SecretString"])
            host, name = secret["DB_HOST"], secret["DB_NAME"]
            port = int(secret.get("DB_PORT") or 5432)
            if not isinstance(host, str) or not host or not isinstance(name, str) or not name:
                raise ValueError
        except Exception as exc:  # noqa: BLE001 - 원인 메시지에 접속 정보가 섞일 수 있어 이름만 남긴다.
            raise DatabaseUnavailableError(f"DB 접속 정보 시크릿을 읽지 못했습니다({type(exc).__name__}).") from None
        _ENDPOINT_CACHE[secret_id] = (host, port, name)
    host, port, name = _ENDPOINT_CACHE[secret_id]
    return settings.db_host or host, settings.db_port or port, settings.db_name or name


def database_label(settings: V3Settings, secret_client: Any = None) -> str:
    """화면·로그용 표기. 호스트 주소는 적지 않고 DB 이름과 포트만 보여 준다."""
    try:
        _, port, name = resolve_endpoint(settings, secret_client)
    except Exception:  # noqa: BLE001 - 표기용이라 실패해도 본 작업을 막지 않는다.
        return "(DB 접속 정보를 읽지 못함)"
    return f"{name}:{port}"


def build_ssl(settings: V3Settings) -> ssl.SSLContext | bool:
    """PGSSLMODE 에 맞는 ssl 인자. 기본 verify-full 이며 RDS CA 번들(PGSSLROOTCERT)이 필요하다."""
    mode = settings.db_ssl_mode
    if mode == "disable":
        return False
    if mode == "require":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    return ssl.create_default_context(cafile=settings.db_ssl_root_cert)


def connect_kwargs(
    settings: V3Settings, user: str, password: str | None, endpoint: tuple[str, int, str] | None = None
) -> dict[str, Any]:
    """asyncpg.connect 인자. 읽기 전용·타임아웃은 서버 설정으로 강제한다. endpoint 는 resolve_endpoint 결과(없으면 settings 값)."""
    if endpoint is None:
        if not settings.db_host or not settings.db_name:
            raise ConfigError("DB host/name 설정이 필요합니다. PGHOST, PGDATABASE 를 확인하세요.")
        endpoint = (settings.db_host, settings.db_port or 5432, settings.db_name)
    host, port, database = endpoint
    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "ssl": build_ssl(settings),
        "timeout": 15,
        "server_settings": {
            "default_transaction_read_only": "on",
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "idle_in_transaction_session_timeout": "30000",
            "application_name": "pill-llm-v3",
        },
    }


_AUTH_ERRORS = ("InvalidPasswordError", "InvalidAuthorizationSpecificationError")


async def open_connection(settings: V3Settings, secret_client: Any = None, connect: Callable[..., Any] | None = None):
    """새 asyncpg 연결 하나. 자격증명은 매번 새로 조회하고, 인증 실패면 다시 읽어 한 번 더 시도한다."""
    if connect is None:
        import asyncpg

        connect = asyncpg.connect

    last_name = "Unknown"
    for attempt in range(2):
        user, password = await asyncio.to_thread(resolve_credentials, settings, secret_client)
        endpoint = await asyncio.to_thread(resolve_endpoint, settings, secret_client)
        try:
            return await connect(**connect_kwargs(settings, user, password, endpoint))
        except ConfigError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_name = type(exc).__name__
            # 회전 직후라면 방금 읽은 값이 이미 낡았을 수 있다 → 시크릿을 다시 읽어 재시도.
            if attempt == 0 and last_name in _AUTH_ERRORS and settings.rds_secret_arn:
                logger.warning("DB 인증 실패 - 시크릿을 다시 읽어 재시도합니다.")
                continue
            break
    raise DatabaseUnavailableError(f"DB 연결에 실패했습니다({last_name}).") from None


# --------------------------------------------------------------------------- 엔진/Reader

class SqlAlchemyReader:
    """SQLAlchemy AsyncConnection 을 Reader 로 감싼다."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        from sqlalchemy import text

        result = await self._connection.execute(text(sql), dict(params or {}))
        return [dict(row) for row in result.mappings().all()]


def build_engine(settings: V3Settings, secret_client: Any = None, connect: Callable[..., Any] | None = None):
    """v2 전용 엔진. 앱의 app.db.session 엔진과 분리한다(회전하는 마스터 시크릿을 URL 에 고정하지 않기 위해)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    async def creator():
        return await open_connection(settings, secret_client, connect)

    return create_async_engine(
        "postgresql+asyncpg://",
        async_creator=creator,
        pool_size=settings.db_pool_size,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=600,
    )


def reader_factory_for(engine: Any) -> ReaderFactory:
    """검색 1회 = 읽기 전용 REPEATABLE READ 트랜잭션 1개 (공개/정리 중에도 한 스냅샷만 본다)."""

    @asynccontextmanager
    async def open_reader() -> AsyncIterator[Reader]:
        from sqlalchemy import text

        async with engine.connect() as connection:
            # 트랜잭션의 첫 문장이어야 한다.
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            try:
                yield SqlAlchemyReader(connection)
            finally:
                await connection.rollback()

    return open_reader

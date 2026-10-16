"""RDS connection settings are code-owned, independent of .env and DATABASE_URL."""
import asyncio
import json
import ssl
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import create_async_engine

from .aws_auth import client_config, session_for
from .config import Settings


class DatabaseConnectionError(Exception):
    """Sanitized error: never include secret values or raw driver messages."""


@dataclass(frozen=True)
class RDSConfig:
    secret_id: str = "rds!db-71cf9992-e13e-4601-88da-425ac219f336"
    host: str = "pill-check-dev-postgres.c43ekyi6yiie.us-east-1.rds.amazonaws.com"
    database: str = "pill"
    port: int = 5432
    region: str = "us-east-1"


RDS = RDSConfig()
CA_FILE = Path(__file__).with_name("certs") / "us-east-1-bundle.pem"


def read_credentials(settings: Settings, config: RDSConfig = RDS):
    # A fresh AWSCURRENT read on each physical connection supports password rotation.
    client = session_for(settings).client("secretsmanager", region_name=config.region, config=client_config())
    try:
        response = client.get_secret_value(SecretId=config.secret_id, VersionStage="AWSCURRENT")
        secret = json.loads(response["SecretString"])
        username, password = secret["username"], secret["password"]
        if not all(isinstance(value, str) and value for value in (username, password)):
            raise ValueError("Invalid credential fields")
        return username, password
    finally:
        client.close()


def create_database_engine(settings: Settings):
    async def connect():
        try:
            # No connection URL interpolation: special characters in passwords are preserved.
            username, password = await asyncio.to_thread(read_credentials, settings)
            tls = ssl.create_default_context(cafile=str(CA_FILE))
            return await asyncpg.connect(host=RDS.host, port=RDS.port, database=RDS.database,
                user=username, password=password, ssl=tls, timeout=15, command_timeout=30)
        except (BotoCoreError, ClientError, KeyError, TypeError, ValueError, OSError, asyncpg.PostgresError):
            raise DatabaseConnectionError(
                "RDS 연결 실패: EC2 역할의 Secrets Manager 권한, 시크릿 형식, RDS 네트워크 및 DB 권한을 확인하세요."
            ) from None

    return create_async_engine("postgresql+asyncpg://", async_creator=connect,
                               pool_pre_ping=True, pool_recycle=300, hide_parameters=True)

"""설정과 DB 연결 안전장치 테스트 (DB/AWS 없이)."""
import json

from app.llm.v2.config import ConfigError, V2Settings
from app.llm.v2.db import (
    DatabaseUnavailableError,
    build_ssl,
    connect_kwargs,
    open_connection,
    resolve_credentials,
    safe_error_name,
)
from app.llm.v2.tests.helpers import make_settings, raises

SECRET_ARN = "arn:aws:secretsmanager:us-east-1:111111111111:secret:test"


class FakeSecrets:
    """호출할 때마다 다른 비밀번호를 돌려주는 Secrets Manager 가짜 (회전 흉내)."""

    def __init__(self, *passwords: str) -> None:
        self.passwords = list(passwords)
        self.calls = 0

    def get_secret_value(self, SecretId):
        assert SecretId == SECRET_ARN
        self.calls += 1
        password = self.passwords[min(self.calls, len(self.passwords)) - 1]
        return {"SecretString": json.dumps({"username": "master", "password": password})}


def test_region_is_fixed_to_us_east_1():
    assert V2Settings.from_env({}).region == "us-east-1"
    # 환경변수로 바꿀 수 없다
    assert V2Settings.from_env({"AWS_REGION": "ap-northeast-2", "BEDROCK_REGION": "eu-west-1"}).region == "us-east-1"


def test_model_ids_default_to_v1_profiles_and_can_be_overridden():
    settings = V2Settings.from_env({})
    assert settings.haiku_model_id == "us.anthropic.claude-haiku-5-5" and settings.sonnet_model_id == "us.anthropic.claude-sonnet-5-5"
    assert settings.resolved_model_id == settings.haiku_model_id  # 기본은 haiku
    assert V2Settings.from_env({"LLM_V2_DEFAULT_MODEL": "sonnet"}).resolved_model_id == settings.sonnet_model_id
    assert V2Settings.from_env({"LLM_V2_MODEL_ID": "custom", "LLM_V2_DEFAULT_MODEL": "sonnet"}).resolved_model_id == "custom"
    assert V2Settings.from_env({"BEDROCK_MODEL_ID": "anthropic.claude-opus-5-5"}).resolved_model_id == settings.haiku_model_id
    with raises(ConfigError):
        V2Settings.from_env({"LLM_V2_DEFAULT_MODEL": "opus"})


def test_from_env_reads_pipeline_style_names():
    settings = V2Settings.from_env(
        {"PGHOST": "h", "PGDATABASE": "pill", "RDS_SECRET_ARN": SECRET_ARN, "LLM_V2_MODEL_ID": "m"}
    )
    assert settings.db_host == "h" and settings.rds_secret_arn == SECRET_ARN and settings.llm_model_id == "m"
    assert settings.embedding_version == "amazon.titan-embed-text-v2:0:dim=1024:normalize=true"
    assert settings.allow_global_search is False


def test_max_distance_default_and_validation():
    assert V2Settings.from_env({}).max_distance == 0.65
    assert V2Settings.from_env({"LLM_V2_MAX_DISTANCE": "0.5"}).max_distance == 0.5
    for bad in ("-0.1", "2.5", "abc"):
        with raises(ConfigError):
            V2Settings.from_env({"LLM_V2_MAX_DISTANCE": bad})


def test_settings_repr_hides_password():
    assert "pw-for-tests" not in repr(make_settings())


def test_connect_kwargs_force_read_only_and_timeout():
    kwargs = connect_kwargs(make_settings(db_ssl_mode="disable"), "u", "p")
    assert kwargs["server_settings"]["default_transaction_read_only"] == "on"
    assert kwargs["server_settings"]["statement_timeout"] == "15000"
    assert kwargs["ssl"] is False


def test_connect_kwargs_requires_host():
    with raises(ConfigError):
        connect_kwargs(make_settings(db_host=None), "u", "p")


def test_ssl_modes():
    assert build_ssl(make_settings(db_ssl_mode="disable")) is False
    context = build_ssl(make_settings(db_ssl_mode="require"))
    assert context.check_hostname is False
    verified = build_ssl(make_settings(db_ssl_mode="verify-full"))
    assert verified.check_hostname is True


def test_resolve_credentials_reads_secret_every_time():
    secrets = FakeSecrets("first", "second")
    settings = make_settings(rds_secret_arn=SECRET_ARN, db_user=None, db_password=None)
    assert resolve_credentials(settings, secrets) == ("master", "first")
    assert resolve_credentials(settings, secrets) == ("master", "second")
    assert secrets.calls == 2  # 캐시하지 않는다


def test_resolve_credentials_error_does_not_leak():
    class Broken:
        def get_secret_value(self, SecretId):
            raise RuntimeError("password=hunter2 arn=" + SecretId)

    settings = make_settings(rds_secret_arn=SECRET_ARN)
    with raises(DatabaseUnavailableError) as caught:
        resolve_credentials(settings, Broken())
    message = str(caught.value)
    assert "hunter2" not in message and SECRET_ARN not in message
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_resolve_credentials_rejects_malformed_secret():
    class Malformed:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({"username": "u"})}

    with raises(DatabaseUnavailableError):
        resolve_credentials(make_settings(rds_secret_arn=SECRET_ARN), Malformed())


class InvalidPasswordError(Exception):
    """asyncpg 의 같은 이름 예외 흉내 (클래스 이름으로만 판정한다)."""


async def test_open_connection_rereads_secret_after_auth_failure():
    secrets = FakeSecrets("stale", "rotated")
    seen: list[str] = []

    async def connect(**kwargs):
        seen.append(kwargs["password"])
        if kwargs["password"] == "stale":
            raise InvalidPasswordError("password authentication failed")
        return "connection"

    settings = make_settings(rds_secret_arn=SECRET_ARN, db_ssl_mode="disable")
    assert await open_connection(settings, secrets, connect) == "connection"
    assert seen == ["stale", "rotated"]


async def test_open_connection_gives_up_after_one_retry_without_leaking():
    secrets = FakeSecrets("a", "b", "c")

    async def connect(**kwargs):
        raise InvalidPasswordError("password=" + kwargs["password"])

    settings = make_settings(rds_secret_arn=SECRET_ARN, db_ssl_mode="disable")
    with raises(DatabaseUnavailableError) as caught:
        await open_connection(settings, secrets, connect)
    assert secrets.calls == 2
    assert "InvalidPasswordError" in str(caught.value)
    assert "password=" not in str(caught.value)


async def test_open_connection_does_not_retry_other_errors():
    calls = []

    async def connect(**kwargs):
        calls.append(1)
        raise OSError("connection refused to db.invalid")

    with raises(DatabaseUnavailableError) as caught:
        await open_connection(make_settings(db_ssl_mode="disable"), None, connect)
    assert len(calls) == 1
    assert "db.invalid" not in str(caught.value)


def test_safe_error_name_uses_class_and_sqlstate_only():
    class Boom(Exception):
        sqlstate = "28P01"

    assert safe_error_name(Boom("secret detail")) == "Boom(28P01)"
    assert safe_error_name(ValueError("secret detail")) == "ValueError"

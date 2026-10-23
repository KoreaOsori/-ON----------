"""설정과 DB 연결 안전장치 테스트 (DB/AWS 없이)."""
import json

from app.llm.v3.config import ConfigError, V3Settings
from app.llm.v3.db import (
    _ENDPOINT_CACHE,
    database_label,
    resolve_endpoint,
    DatabaseUnavailableError,
    build_ssl,
    connect_kwargs,
    open_connection,
    resolve_credentials,
    safe_error_name,
)
from app.llm.v3.tests.helpers import make_settings, raises

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
    assert V3Settings.from_env({}).region == "us-east-1"
    # 환경변수로 바꿀 수 없다
    assert V3Settings.from_env({"AWS_REGION": "ap-northeast-2", "BEDROCK_REGION": "eu-west-1"}).region == "us-east-1"


def test_model_ids_default_to_v1_profiles_and_can_be_overridden():
    settings = V3Settings.from_env({})
    assert settings.haiku_model_id == "us.anthropic.claude-haiku-5-5" and settings.sonnet_model_id == "us.anthropic.claude-sonnet-5-5"
    assert settings.resolved_model_id == settings.haiku_model_id  # 기본은 haiku
    assert V3Settings.from_env({"LLM_V3_DEFAULT_MODEL": "sonnet"}).resolved_model_id == settings.sonnet_model_id
    assert V3Settings.from_env({"LLM_V3_MODEL_ID": "custom", "LLM_V3_DEFAULT_MODEL": "sonnet"}).resolved_model_id == "custom"
    assert V3Settings.from_env({"BEDROCK_MODEL_ID": "anthropic.claude-opus-5-5"}).resolved_model_id == settings.haiku_model_id
    with raises(ConfigError):
        V3Settings.from_env({"LLM_V3_DEFAULT_MODEL": "opus"})


def test_from_env_reads_pipeline_style_names():
    settings = V3Settings.from_env(
        {"PGHOST": "h", "PGDATABASE": "pill", "RDS_SECRET_ARN": SECRET_ARN, "LLM_V3_MODEL_ID": "m"}
    )
    assert settings.db_host == "h" and settings.rds_secret_arn == SECRET_ARN and settings.llm_model_id == "m"
    assert settings.embedding_version == "amazon.titan-embed-text-v2:0:dim=1024:normalize=true"
    assert settings.allow_global_search is False


def test_max_distance_default_and_validation():
    assert V3Settings.from_env({}).max_distance == 0.80
    assert V3Settings.from_env({"LLM_V3_MAX_DISTANCE": "0.5"}).max_distance == 0.5
    for bad in ("-0.1", "2.5", "abc"):
        with raises(ConfigError):
            V3Settings.from_env({"LLM_V3_MAX_DISTANCE": bad})


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


class FakeAppSecret:
    """pill-check/dev/app 가짜. DB_HOST, DB_PORT, DB_NAME 과 쓰지 않는 값들을 담는다."""

    def __init__(self, payload=None):
        self.payload = payload or {"DB_HOST": "db.example.internal", "DB_PORT": "5433", "DB_NAME": "pilldb", "DB_PASSWORD": "never-used"}
        self.calls = 0

    def get_secret_value(self, SecretId):
        assert SecretId == "pill-check/dev/app"
        self.calls += 1
        return {"SecretString": json.dumps(self.payload)}


def test_resolve_endpoint_reads_app_secret_once_and_caches():
    _ENDPOINT_CACHE.clear()
    secrets = FakeAppSecret()
    settings = make_settings(db_host=None, db_name=None, app_secret_id="pill-check/dev/app")
    assert resolve_endpoint(settings, secrets) == ("db.example.internal", 5433, "pilldb")
    assert resolve_endpoint(settings, secrets) == ("db.example.internal", 5433, "pilldb")
    assert secrets.calls == 1  # 위치는 바뀌지 않아 한 번만 읽는다
    assert database_label(settings, secrets) == "pilldb:5433" and "example" not in database_label(settings, secrets)
    _ENDPOINT_CACHE.clear()


def test_resolve_endpoint_defaults_port_and_lets_env_win():
    _ENDPOINT_CACHE.clear()
    secrets = FakeAppSecret({"DB_HOST": "h1", "DB_NAME": "n1"})
    settings = make_settings(db_host=None, db_name=None, app_secret_id="pill-check/dev/app")
    assert resolve_endpoint(settings, secrets) == ("h1", 5432, "n1")
    override = make_settings(db_host=None, db_name="other", db_port=6000, app_secret_id="pill-check/dev/app")
    assert resolve_endpoint(override, secrets) == ("h1", 6000, "other")
    full = make_settings(db_host="localhost", db_name="pill", app_secret_id=None)
    assert resolve_endpoint(full, secrets) == ("localhost", 5432, "pill") and secrets.calls == 1
    _ENDPOINT_CACHE.clear()


def test_resolve_endpoint_without_any_source_is_config_error():
    with raises(ConfigError):
        resolve_endpoint(make_settings(db_host=None, db_name=None, app_secret_id=None))
    with raises(ConfigError):
        resolve_endpoint(make_settings(db_host="h", db_name=None, app_secret_id=None))


def test_resolve_endpoint_errors_do_not_leak():
    _ENDPOINT_CACHE.clear()

    class Broken:
        def get_secret_value(self, SecretId):
            raise RuntimeError("host=secret-host.internal secret=" + SecretId)

    settings = make_settings(db_host=None, db_name=None, app_secret_id="pill-check/dev/app")
    with raises(DatabaseUnavailableError) as caught:
        resolve_endpoint(settings, Broken())
    message = str(caught.value)
    assert "secret-host" not in message and "pill-check/dev/app" not in message and caught.value.__cause__ is None
    for payload in ({"DB_HOST": "h"}, {"DB_HOST": "", "DB_NAME": "n"}, {"DB_NAME": "n"}):
        with raises(DatabaseUnavailableError):
            resolve_endpoint(settings, FakeAppSecret(payload))
    assert _ENDPOINT_CACHE == {}  # 실패는 캐시하지 않는다
    assert database_label(settings, Broken()) == "(DB 접속 정보를 읽지 못함)"


async def test_open_connection_connects_to_endpoint_from_app_secret():
    _ENDPOINT_CACHE.clear()

    class Both:
        def __init__(self):
            self.app = FakeAppSecret()

        def get_secret_value(self, SecretId):
            if SecretId == "pill-check/dev/app":
                return self.app.get_secret_value(SecretId)
            return {"SecretString": json.dumps({"username": "master", "password": "pw"})}

    seen = {}

    async def connect(**kwargs):
        seen.update(kwargs)
        return "connection"

    settings = make_settings(
        db_host=None, db_name=None, app_secret_id="pill-check/dev/app", rds_secret_arn="rds-secret", db_ssl_mode="disable"
    )
    assert await open_connection(settings, Both(), connect) == "connection"
    assert (seen["host"], seen["port"], seen["database"], seen["user"]) == ("db.example.internal", 5433, "pilldb", "master")
    assert "never-used" not in repr(seen)  # 앱 시크릿의 다른 값(DB_PASSWORD 등)은 쓰지 않는다
    _ENDPOINT_CACHE.clear()


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


def test_contra_db_path_from_env():
    assert V3Settings.from_env({}).contra_db_path == ""
    assert V3Settings.from_env({"LLM_V3_CONTRA_DB": "/x/contra.sqlite"}).contra_db_path == "/x/contra.sqlite"


def test_contra_source_from_env():
    assert V3Settings.from_env({}).contra_source == "auto"
    for value in ("rds", "SQLite", "off", "auto"):
        assert V3Settings.from_env({"LLM_V3_CONTRA_SOURCE": value}).contra_source == value.lower()
    with raises(ConfigError):
        V3Settings.from_env({"LLM_V3_CONTRA_SOURCE": "csv"})


def test_api_settings_from_env():
    defaults = V3Settings.from_env({})
    assert (defaults.api_max_concurrency, defaults.api_queue_seconds) == (4, 5.0)
    assert not hasattr(defaults, "api_key")  # v3 는 X-API-Key 인증을 쓰지 않는다
    custom = V3Settings.from_env({"LLM_V3_API_MAX_CONCURRENCY": "0", "LLM_V3_API_QUEUE_SECONDS": "-3"})
    assert custom.api_max_concurrency == 1 and custom.api_queue_seconds == 0.0  # 하한으로 보정


def test_db_location_comes_from_app_secret_when_pghost_is_unset():
    from app.llm.v3.config import DEFAULT_APP_SECRET_ID, DEFAULT_DB_CA_FILE, DEFAULT_DB_SECRET_ID

    settings = V3Settings.from_env({})
    assert (settings.db_host, settings.db_port, settings.db_name) == (None, None, None)  # 코드에 주소를 적지 않는다
    assert settings.app_secret_id == DEFAULT_APP_SECRET_ID == "pill-check/dev/app"
    assert settings.rds_secret_arn == DEFAULT_DB_SECRET_ID
    assert settings.db_ssl_mode == "verify-full" and settings.db_ssl_root_cert == DEFAULT_DB_CA_FILE
    assert DEFAULT_DB_CA_FILE.replace("\\", "/").endswith("/llm/v3/certs/us-east-1-bundle.pem")  # v1 파일을 참조하지 않는다
    assert settings.db_password is None
    assert V3Settings.from_env({"DB_SECRET_ID": "other/secret"}).app_secret_id == "other/secret"


def test_no_rds_hostname_is_hardcoded_in_v2_sources():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders = [
        str(path.relative_to(root))
        for path in list(root.glob("*.py")) + list(root.glob("evaluation/*.py")) + [root / "README.md"]
        if "c43ekyi6yiie" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_pghost_switches_to_env_only_for_local_dev_db():
    local = V3Settings.from_env(
        {"PGHOST": "localhost", "PGPORT": "5433", "PGDATABASE": "pill", "PGUSER": "pill_dev", "PGPASSWORD": "pw", "PGSSLMODE": "disable"}
    )
    assert (local.db_host, local.db_port, local.db_name, local.db_user) == ("localhost", 5433, "pill", "pill_dev")
    assert local.rds_secret_arn is None  # 로컬 DB 에는 고정 RDS 시크릿을 쓰지 않는다
    assert local.db_ssl_root_cert is None and local.db_ssl_mode == "disable"
    no_db = V3Settings.from_env({"PGHOST": "localhost"})
    assert no_db.db_name is None and no_db.rds_secret_arn is None  # 일부만 주면 나머지는 비워 둔다(오류로 드러남)


def test_env_overrides_secret_values_individually():
    settings = V3Settings.from_env({"PGDATABASE": "other", "RDS_SECRET_ARN": SECRET_ARN, "PGSSLROOTCERT": "/x/ca.pem", "PGPORT": "6543"})
    assert settings.db_name == "other" and settings.rds_secret_arn == SECRET_ARN and settings.db_ssl_root_cert == "/x/ca.pem"
    assert settings.db_host is None and settings.db_port == 6543 and settings.app_secret_id == "pill-check/dev/app"


def test_default_ca_applies_only_to_rds_hosts():
    from app.llm.v3.config import DEFAULT_DB_CA_FILE

    rds = V3Settings.from_env({"PGHOST": "mydb.abc.us-east-1.rds.amazonaws.com", "PGDATABASE": "pill", "RDS_SECRET_ARN": SECRET_ARN})
    assert rds.db_ssl_root_cert == DEFAULT_DB_CA_FILE
    other = V3Settings.from_env({"PGHOST": "db.example.com", "PGDATABASE": "pill"})
    assert other.db_ssl_root_cert is None


def test_bundled_rds_ca_file_exists_and_is_a_valid_trust_bundle():
    import ssl
    from pathlib import Path

    from app.llm.v3.config import DEFAULT_DB_CA_FILE

    path = Path(DEFAULT_DB_CA_FILE)
    assert path.is_file() and "v1" not in path.parts
    text = path.read_text(encoding="ascii")
    assert text.count("-----BEGIN CERTIFICATE-----") == text.count("-----END CERTIFICATE-----") >= 1
    assert "PRIVATE KEY" not in text  # 공개 신뢰 앵커만 들어 있어야 한다
    context = ssl.create_default_context(cafile=str(path))
    subjects = [dict(item[0] for item in cert["subject"]) for cert in context.get_ca_certs()]
    assert subjects and all("Amazon RDS" in subject.get("organizationalUnitName", "") for subject in subjects)
    assert build_ssl(make_settings(db_ssl_mode="verify-full", db_ssl_root_cert=str(path))).verify_mode == ssl.CERT_REQUIRED


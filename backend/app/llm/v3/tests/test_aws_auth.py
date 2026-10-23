"""AWS 자격증명 정책 테스트: EC2 에서는 인스턴스 역할만 허용, 로컬은 완화 (AWS/네트워크 호출 없음)."""
from app.llm.v3.aws_auth import CredentialPolicyError, ensure_credentials, is_strict, running_on_ec2
from app.llm.v3.config import ConfigError, V3Settings
from app.llm.v3.tests.helpers import make_settings, raises


class Credentials:
    def __init__(self, method):
        self.method = method


class Session:
    def __init__(self, credentials):
        self._credentials = credentials
        self.calls = 0

    def get_credentials(self):
        self.calls += 1
        return self._credentials


def factory_for(session):
    return lambda region: session


def files(mapping):
    return lambda path: mapping.get(path, "")


def test_running_on_ec2_detects_nitro_and_xen():
    vendor = "/sys/devices/virtual/dmi/id/sys_vendor"
    assert running_on_ec2(files({vendor: "Amazon EC2\n"})) is True  # Nitro (t3 등)
    assert running_on_ec2(files({"/sys/hypervisor/uuid": "ec2e1916-9099-7caf"})) is True  # Xen
    assert running_on_ec2(files({"/sys/devices/virtual/dmi/id/product_uuid": "EC2ABCDE-1111"})) is True
    assert running_on_ec2(files({vendor: "LENOVO"})) is False
    assert running_on_ec2(files({})) is False  # 파일이 없는 환경(Windows·macOS)


def test_mode_decides_strictness():
    assert is_strict(make_settings(auth_mode="ec2_role"), on_ec2=lambda: False) is True
    assert is_strict(make_settings(auth_mode="default_chain"), on_ec2=lambda: True) is False
    assert is_strict(make_settings(auth_mode="auto"), on_ec2=lambda: True) is True  # EC2 위: 엄격
    assert is_strict(make_settings(auth_mode="auto"), on_ec2=lambda: False) is False  # 로컬: 완화


def test_strict_accepts_only_instance_role_credentials():
    ok = Session(Credentials("iam-role"))
    assert ensure_credentials(make_settings(auth_mode="ec2_role"), factory_for(ok)) == "iam-role"
    for method in ("env", "shared-credentials-file", "sso", "assume-role", "container-role", "None"):
        session = Session(Credentials(method))
        with raises(CredentialPolicyError) as caught:
            ensure_credentials(make_settings(auth_mode="ec2_role"), factory_for(session))
        assert f"현재 자격증명 방식: {method}" in str(caught.value) and "default_chain" in str(caught.value)


def test_strict_rejects_missing_credentials():
    with raises(CredentialPolicyError) as caught:
        ensure_credentials(make_settings(auth_mode="ec2_role"), factory_for(Session(None)))
    assert "IAM 역할" in str(caught.value)


def test_relaxed_mode_never_touches_credentials():
    session = Session(Credentials("env"))
    assert ensure_credentials(make_settings(auth_mode="default_chain"), factory_for(session)) is None
    assert ensure_credentials(make_settings(auth_mode="auto"), factory_for(session), on_ec2=lambda: False) is None
    assert session.calls == 0  # 로컬에서는 자격증명 조회조차 하지 않는다


def test_auto_on_ec2_blocks_static_keys():
    session = Session(Credentials("env"))
    with raises(CredentialPolicyError):
        ensure_credentials(make_settings(auth_mode="auto"), factory_for(session), lambda: True)


def test_error_message_has_no_secret_values():
    class Leaky(Credentials):
        access_key = "AKIA-SECRET-ACCESS-KEY"
        secret_key = "SECRET-VALUE"

    with raises(CredentialPolicyError) as caught:
        ensure_credentials(make_settings(auth_mode="ec2_role"), factory_for(Session(Leaky("env"))))
    assert "AKIA" not in str(caught.value) and "SECRET" not in str(caught.value)


def test_policy_error_is_a_config_error():
    assert issubclass(CredentialPolicyError, ConfigError)


def test_auth_mode_from_env():
    assert V3Settings.from_env({}).auth_mode == "auto"
    assert V3Settings.from_env({"LLM_V3_AUTH_MODE": "EC2_ROLE"}).auth_mode == "ec2_role"
    assert V3Settings.from_env({"LLM_V3_AUTH_MODE": "default_chain"}).auth_mode == "default_chain"
    with raises(ConfigError):
        V3Settings.from_env({"LLM_V3_AUTH_MODE": "anything"})

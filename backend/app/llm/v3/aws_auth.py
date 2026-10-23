"""AWS 자격증명 정책: EC2 에서는 인스턴스 역할(instance profile)만 허용한다.

- 정적 키(AWS_ACCESS_KEY_ID 등)나 공유 프로필이 우연히 먼저 잡혀 운영 서버가 역할이 아닌 자격증명으로 Bedrock·Secrets Manager 를
  호출하는 일을 막는다. 권한을 역할 하나로 관리하기 위한 장치이며, v1(`backend/app/llm/v1/aws_auth.py`)과 같은 검사다.
- 모드(LLM_V3_AUTH_MODE)
    auto (기본)  EC2 위에서 실행 중이면 엄격(ec2_role), 아니면 완화(default_chain). 로컬 개발은 설정 없이 그대로 동작한다.
    ec2_role     항상 엄격. 컨테이너 등에서 EC2 감지가 안 될 수 있으니 운영 서버에는 이 값을 명시하는 편이 안전하다.
    default_chain 항상 완화(boto3 기본 자격증명 체인). 로컬 개발·평가용.
- 감지 실패는 '완화'로 이어지므로(fail-open), 운영 배포에서는 ec2_role 을 명시하는 것을 권한다.
- 자격증명 값은 읽거나 기록하지 않는다. 방식 이름(예: env, iam-role)만 오류 메시지에 쓴다.
"""
import logging
from typing import Any, Callable

from app.llm.v3.config import ConfigError, V3Settings

logger = logging.getLogger(__name__)

EC2_ROLE_METHOD = "iam-role"  # botocore 가 EC2 인스턴스 메타데이터(IMDS)에서 얻은 자격증명에 붙이는 이름

_DMI_VENDOR_FILES = (
    "/sys/devices/virtual/dmi/id/sys_vendor",
    "/sys/devices/virtual/dmi/id/board_vendor",
    "/sys/devices/virtual/dmi/id/bios_vendor",
)
_UUID_FILES = ("/sys/devices/virtual/dmi/id/product_uuid", "/sys/hypervisor/uuid")


class CredentialPolicyError(ConfigError):
    """자격증명 정책 위반. 메시지에는 비밀값을 넣지 않는다."""


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            return handle.read(256).strip()
    except OSError:
        return ""


def running_on_ec2(read: Callable[[str], str] | None = None) -> bool:
    """리눅스 DMI/하이퍼바이저 정보로 EC2 여부를 판단한다(네트워크 호출 없음). Windows·macOS 는 항상 False."""
    read = read or _read_text
    if any("amazon ec2" in read(path).lower() for path in _DMI_VENDOR_FILES):
        return True
    return any(read(path).lower().startswith("ec2") for path in _UUID_FILES)  # Xen 계열(구형 인스턴스)


def is_strict(settings: V3Settings, on_ec2: Callable[[], bool] | None = None) -> bool:
    if settings.auth_mode == "ec2_role":
        return True
    if settings.auth_mode == "default_chain":
        return False
    return (on_ec2 or running_on_ec2)()


def _default_session(region: str) -> Any:
    import boto3

    return boto3.Session(region_name=region)


def ensure_credentials(
    settings: V3Settings,
    session_factory: Callable[[str], Any] | None = None,
    on_ec2: Callable[[], bool] | None = None,
) -> str | None:
    """엄격 모드면 자격증명이 EC2 역할에서 온 것인지 확인하고 방식 이름을 돌려준다. 완화 모드면 아무것도 하지 않고 None."""
    if not is_strict(settings, on_ec2):
        logger.info("AWS 자격증명 정책: 완화(default_chain)")
        return None
    session = (session_factory or _default_session)(settings.region)
    credentials = session.get_credentials()
    if credentials is None:
        raise CredentialPolicyError(
            "AWS 자격증명을 찾을 수 없습니다. EC2 인스턴스에 IAM 역할(instance profile)을 연결하고 IMDS 접근을 확인하세요."
        )
    method = str(getattr(credentials, "method", None))
    if method != EC2_ROLE_METHOD:
        raise CredentialPolicyError(
            f"EC2 인스턴스 역할 자격증명이 필요합니다(현재 자격증명 방식: {method}). 서버 환경의 AWS_ACCESS_KEY_ID·AWS_PROFILE 등을 "
            "제거하세요. 로컬 개발이라면 LLM_V3_AUTH_MODE=default_chain 으로 설정하세요."
        )
    logger.info("AWS 자격증명 정책: 엄격(EC2 역할 확인)")
    return method

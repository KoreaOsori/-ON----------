"""Refreshable SDK credentials; never copy temporary keys into a client."""
import boto3
from botocore.config import Config
from botocore.exceptions import NoCredentialsError

from .config import Settings


class RoleCredentialsError(ValueError):
    pass


def session_for(settings: Settings):
    session = boto3.Session(region_name=settings.region)
    credentials = session.get_credentials()
    if credentials is None:
        raise NoCredentialsError()
    if settings.auth_mode == "ec2_role" and credentials.method != "iam-role":
        raise RoleCredentialsError(
            "EC2 instance profile 자격증명이 필요합니다. EC2 역할 연결과 IMDS 접근을 확인하고 "
            "우선 적용되는 AWS 환경변수·프로필 자격증명을 제거하세요. "
            "로컬 테스트는 LLM_V1_AUTH_MODE=default_chain으로 설정하세요."
        )
    return session


def client_config():
    # Explicit SigV4 prevents a Bedrock bearer-token configuration from replacing role authentication.
    return Config(signature_version="v4", connect_timeout=5, read_timeout=90,
                  retries={"mode": "standard", "max_attempts": 2})

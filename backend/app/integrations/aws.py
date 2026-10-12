from functools import lru_cache

import boto3
from botocore.config import Config

from app.core.config import settings

_config = Config(region_name=settings.aws_region, signature_version="s3v4", retries={"mode": "standard"})


@lru_cache
def s3_client():
    """서버 내부용 S3 클라이언트 (LocalStack 사용 시 aws_endpoint_url)"""
    return boto3.client("s3", endpoint_url=settings.aws_endpoint_url, config=_config)


@lru_cache
def s3_presign_client():
    """브라우저에 전달할 presigned URL 생성용. 로컬에서는 브라우저가 접근 가능한 엔드포인트를 사용한다."""
    endpoint = settings.s3_public_endpoint_url or settings.aws_endpoint_url
    return boto3.client("s3", endpoint_url=endpoint, config=_config)


@lru_cache
def textract_client():
    return boto3.client("textract", endpoint_url=settings.aws_endpoint_url, config=_config)

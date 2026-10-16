"""Adapters for the existing EC2 role, Silver pointer and RDS secret."""
import json
import os
from datetime import date
from config import settings


def client(service):
    import boto3
    region = settings()["aws"]["region"]
    if not region:
        raise ValueError("AWS_REGION 설정이 필요합니다.")
    return boto3.client(service, region_name=region)


def silver_sources(bucket, prefix="silver", snapshot=None, s3=None):
    if not bucket or "/" in bucket or ":" in bucket:
        raise ValueError("DATA_BUCKET에는 버킷 이름만 지정하세요.")
    prefix = prefix.strip("/")
    if not prefix or any(p in (".", "..") for p in prefix.split("/")):
        raise ValueError("잘못된 Silver prefix입니다.")
    s3 = s3 or client("s3")
    # Even a date-selected run must be covered by the successful build pointer.
    response = s3.get_object(Bucket=bucket, Key=f"{prefix}/_latest.json")
    try:
        pointer = json.loads(response["Body"].read())
    finally:
        response["Body"].close()
    selected = snapshot or pointer["snapshot"]
    if date.fromisoformat(selected).isoformat() != selected:
        raise ValueError("snapshot은 YYYY-MM-DD 형식이어야 합니다.")
    tables = ("drug_product", "health_food_product")
    if selected != pointer["snapshot"] or any(pointer.get("tables", {}).get(t) != selected for t in tables):
        raise ValueError("Silver 완료 포인터와 두 제품 테이블의 snapshot이 일치해야 합니다.")
    return {t: f"s3://{bucket}/{prefix}/{t}/snapshot={selected}/data.parquet" for t in tables}


def database_options(secret_client=None):
    db = settings()["database"]
    options = {"host": db["host"], "port": db["port"], "dbname": db["name"],
               "sslmode": db["sslmode"], "sslrootcert": db["sslrootcert"]}
    secret_id = db["secret_id"]
    if secret_id:
        response = (secret_client or client("secretsmanager")).get_secret_value(SecretId=secret_id)
        secret = json.loads(response["SecretString"])
        # Resolve on each connection so RDS password rotations are respected.
        options.update(user=secret["username"], password=secret["password"])
    if not all(options.get(k) for k in ("host", "dbname", "user")):
        raise ValueError("settings.toml DB 설정 및 시크릿의 username/password를 확인하세요.")
    return options

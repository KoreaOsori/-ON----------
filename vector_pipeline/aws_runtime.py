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
    tables = ("drug_product", "health_food_product")
    available = {}
    for table in tables:
        base = f"{prefix}/{table}/"
        found = {}
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=base):
            for obj in page.get("Contents", []):
                relative = obj["Key"][len(base):].split("/")
                if len(relative) != 2 or relative[1] != "data.parquet" or obj.get("Size", 0) <= 0:
                    continue
                value = relative[0].removeprefix("snapshot=")
                try:
                    valid = date.fromisoformat(value).isoformat() == value
                except ValueError:
                    valid = False
                if not valid:
                    continue
                if value in found:
                    raise ValueError(f"같은 날짜의 경로가 중복됩니다: {table}/{value}")
                found[value] = obj["Key"]
        available[table] = found
    common = set(available[tables[0]]) & set(available[tables[1]])
    if not common or (snapshot and snapshot not in common):
        raise ValueError("두 제품의 data.parquet이 모두 있는 날짜가 없습니다.")
    selected = snapshot or max(common)
    return {t: f"s3://{bucket}/{available[t][selected]}" for t in tables}


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

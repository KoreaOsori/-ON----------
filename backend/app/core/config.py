import json
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(.env) 기반 설정. 변수명은 대문자로 매핑된다. (예: DATABASE_URL)"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 앱
    app_name: str = "yakon-backend"
    app_env: Literal["local", "dev", "prod", "test"] = "local"
    debug: bool = False
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"

    # 데이터베이스 / 캐시
    database_url: str = "postgresql+asyncpg://yakon:yakon@localhost:5555/yakon"
    database_echo: bool = False
    # AWS(ECS): RDS 관리형 비밀번호를 Secrets Manager 에서 주입받으므로 개별 값으로 받아 URL 을 조립한다.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "yakon"
    db_username: str | None = None
    db_password: str | None = None
    # AWS(EC2): 앱 시크릿. DB_HOST 를 주지 않으면 DB 접속 정보(DB_HOST·DB_PORT·DB_NAME·DB_USERNAME·DB_PASSWORD)를,
    # PUBLIC_DATA_SERVICE_KEY 를 주지 않으면 공공데이터 키(E_Drug_API)를 여기서 읽는다. 인증은 EC2 IAM 역할
    db_secret_id: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    # AWS 공통 (ECS에서는 Task Role 자격증명을 사용하므로 키를 넣지 않는다)
    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None  # 로컬 LocalStack: http://localstack:4566

    # S3 업로드
    s3_upload_bucket: str = "yakon-local-uploads"
    s3_public_endpoint_url: str | None = None  # 브라우저가 접근할 presigned URL 엔드포인트 (로컬 전용)
    s3_presign_expires_seconds: int = 300
    upload_max_bytes: int = 10 * 1024 * 1024

    # Amazon Bedrock (Claude)
    bedrock_enabled: bool = False
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-opus-5-5"
    bedrock_fallback_model_id: str | None = "anthropic.claude-opus-4-8"
    bedrock_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    bedrock_max_tokens: int = 16000

    # 처방전 OCR: textract 는 한국어 미지원 → 한국어 처방전은 claude(비전) 권장
    ocr_provider: Literal["mock", "claude", "textract"] = "mock"

    # 의약품 데이터: gold = 데이터 파이프라인이 RDS 에 적재한 gold 스키마 / mock = 가상 데이터 (테스트·DB 없는 로컬) / public_api = 공공데이터 (data.go.kr) e약은요
    drug_data_source: Literal["mock", "public_api", "gold"] = "mock"
    public_data_service_key: str | None = None

    # 인증
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    demo_login_enabled: bool = False

    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    oauth_redirect_base_url: str = Field(
        default="http://localhost:3000/auth/callback",
        description="OAuth redirect_uri 기본 경로. 실제 값은 {base}/{provider}",
    )

    # 서비스 정책
    guest_daily_question_limit: int = 8

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if self.db_secret_id and not (self.db_host and self.public_data_service_key):
            self._load_app_secret()
        if self.db_host and self.db_username and self.db_password:
            password = quote_plus(self.db_password)
            self.database_url = f"postgresql+asyncpg://{self.db_username}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
        return self

    def _load_app_secret(self) -> None:
        """환경변수로 이미 준 값은 그대로 두고, 없는 값만 시크릿에서 채운다."""
        import boto3

        response = boto3.client("secretsmanager", region_name=self.aws_region).get_secret_value(
            SecretId=self.db_secret_id
        )
        secret = json.loads(response["SecretString"])
        if not self.db_host:
            self.db_host = secret["DB_HOST"]
            self.db_port = int(secret.get("DB_PORT") or 5432)
            self.db_name = secret["DB_NAME"]
            self.db_username = secret["DB_USERNAME"]
            self.db_password = secret["DB_PASSWORD"]
        if not self.public_data_service_key:
            self.public_data_service_key = secret.get("E_Drug_API")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

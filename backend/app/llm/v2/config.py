"""v2 전용 설정.

- 백엔드의 app.core.config 는 건드리지 않고(= v2 밖 수정 금지) 환경변수에서 직접 읽는다.
- DB/임베딩 환경변수 이름은 vector_pipeline 과 동일하게 맞췄다(PGHOST, RDS_SECRET_ARN ...). 리전은 환경변수 없이 us-east-1 로 고정.
- 비밀값(DB 비밀번호)은 repr/로그에 남지 않도록 repr=False 로 둔다.
  RDS_SECRET_ARN 이 있으면 비밀번호는 여기에 저장하지 않고 연결을 만들 때마다 Secrets Manager 에서 읽는다.
"""
import os
from dataclasses import dataclass, field
from typing import Mapping


class ConfigError(ValueError):
    """설정 누락/오류. 메시지에는 비밀값을 넣지 않는다."""


# vector_pipeline 의 EmbeddingConfig 와 같은 값이어야 DB(pipeline_config)와 일치한다.
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
SCHEMA_VERSION = 2

# 리전은 us-east-1 로 고정한다(환경변수로 바꾸지 않는다). 임베딩·Claude·Secrets Manager 모두 이 리전을 쓴다.
REGION = "us-east-1"

# 비교 대상 Claude 모델. backend/app/llm/v1/config.py 의 기본값(us. 추론 프로파일 ID)과 같은 값이다.
# 이 값은 v1 쪽 설정을 그대로 가져온 것이며 v2 에서 실제 호출로 확인하지 않았다.
DEFAULT_HAIKU_MODEL_ID = "us.anthropic.claude-haiku-5-5"
DEFAULT_SONNET_MODEL_ID = "us.anthropic.claude-sonnet-5-5"


def _first(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value:
            return value
    return None


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} 는 정수여야 합니다.") from None


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} 는 숫자여야 합니다.") from None


@dataclass(frozen=True)
class V2Settings:
    # --- AWS ---
    region: str = REGION
    embedding_model_id: str = EMBEDDING_MODEL_ID
    embedding_dimensions: int = 1024

    # --- DB (읽기 전용 연결) ---
    db_host: str | None = None
    db_port: int = 5432
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = field(default=None, repr=False)
    rds_secret_arn: str | None = None
    db_ssl_mode: str = "verify-full"
    db_ssl_root_cert: str | None = None
    db_statement_timeout_ms: int = 15000
    db_pool_size: int = 3

    # --- Claude (도구 호출 루프) ---
    llm_provider: str = "bedrock"  # bedrock(InvokeModel, EC2 역할) | mantle(bedrock-mantle)
    haiku_model_id: str = DEFAULT_HAIKU_MODEL_ID
    sonnet_model_id: str = DEFAULT_SONNET_MODEL_ID
    default_model: str = "haiku"  # haiku | sonnet
    llm_model_id: str | None = None  # 지정하면 위 두 값보다 우선(임의 모델 ID)
    llm_max_tokens: int = 2000

    # --- 하니스 한도 ---
    max_tool_rounds: int = 4
    max_tool_calls: int = 6
    max_seconds: float = 60.0
    max_question_chars: int = 500

    # --- 검색 정책 ---
    search_top_k: int = 5
    # 코사인 거리가 이 값보다 큰 근거는 버린다(관련 없는 문단을 모델에 주지 않기 위해). 0~2.
    # v1 의 초기값(0.65)과 같다. 실제 평가 데이터(retrieval_eval 의 거리 출력)로 조정해야 한다.
    max_distance: float = 0.65
    # 제품명 없이 전체를 exact 스캔하는 검색. 느릴 수 있어 기본은 끈다.
    allow_global_search: bool = False

    @property
    def embedding_version(self) -> str:
        """vector_pipeline.EmbeddingConfig.version 과 같은 문자열 (DB pipeline_config 와 대조)."""
        return f"{self.embedding_model_id}:dim={self.embedding_dimensions}:normalize=true"

    @property
    def resolved_model_id(self) -> str:
        if self.llm_model_id:
            return self.llm_model_id
        return self.sonnet_model_id if self.default_model == "sonnet" else self.haiku_model_id

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "V2Settings":
        env = os.environ if env is None else env
        dimensions = _int(env, "EMBEDDING_DIMENSIONS", 1024)
        if dimensions not in (256, 512, 1024):
            raise ConfigError("EMBEDDING_DIMENSIONS 는 256, 512, 1024 중 하나여야 합니다.")
        model = env.get("EMBEDDING_MODEL_ID") or EMBEDDING_MODEL_ID
        if model != EMBEDDING_MODEL_ID:
            raise ConfigError("현재는 Titan Text Embeddings V2 만 지원합니다.")

        provider = (env.get("LLM_V2_PROVIDER") or "bedrock").lower()
        if provider not in ("bedrock", "mantle"):
            raise ConfigError("LLM_V2_PROVIDER 는 bedrock 또는 mantle 이어야 합니다.")

        ssl_mode = env.get("PGSSLMODE") or "verify-full"
        if ssl_mode not in ("verify-full", "require", "disable"):
            raise ConfigError("PGSSLMODE 는 verify-full, require, disable 중 하나여야 합니다.")

        max_distance = _float(env, "LLM_V2_MAX_DISTANCE", 0.65)
        if not 0 <= max_distance <= 2:
            raise ConfigError("LLM_V2_MAX_DISTANCE 는 0 이상 2 이하여야 합니다.")

        default_model = (env.get("LLM_V2_DEFAULT_MODEL") or "haiku").lower()
        if default_model not in ("haiku", "sonnet"):
            raise ConfigError("LLM_V2_DEFAULT_MODEL 은 haiku 또는 sonnet 이어야 합니다.")

        return cls(
            region=REGION,
            embedding_model_id=model,
            embedding_dimensions=dimensions,
            db_host=_first(env, "PGHOST", "DB_HOST"),
            db_port=int(_first(env, "PGPORT", "DB_PORT") or 5432),
            db_name=_first(env, "PGDATABASE", "DB_NAME"),
            db_user=_first(env, "PGUSER", "DB_USERNAME"),
            db_password=_first(env, "PGPASSWORD", "DB_PASSWORD"),
            rds_secret_arn=env.get("RDS_SECRET_ARN") or None,
            db_ssl_mode=ssl_mode,
            db_ssl_root_cert=env.get("PGSSLROOTCERT") or None,
            db_statement_timeout_ms=_int(env, "LLM_V2_DB_STATEMENT_TIMEOUT_MS", 15000),
            db_pool_size=_int(env, "LLM_V2_DB_POOL_SIZE", 3),
            llm_provider=provider,
            haiku_model_id=env.get("LLM_V2_HAIKU_MODEL_ID") or DEFAULT_HAIKU_MODEL_ID,
            sonnet_model_id=env.get("LLM_V2_SONNET_MODEL_ID") or DEFAULT_SONNET_MODEL_ID,
            default_model=default_model,
            llm_model_id=env.get("LLM_V2_MODEL_ID") or None,
            llm_max_tokens=_int(env, "LLM_V2_MAX_TOKENS", 2000),
            max_tool_rounds=_int(env, "LLM_V2_MAX_TOOL_ROUNDS", 4),
            max_tool_calls=_int(env, "LLM_V2_MAX_TOOL_CALLS", 6),
            max_seconds=_float(env, "LLM_V2_MAX_SECONDS", 60.0),
            search_top_k=_int(env, "LLM_V2_SEARCH_TOP_K", 5),
            max_distance=max_distance,
            allow_global_search=(env.get("LLM_V2_ALLOW_GLOBAL_SEARCH", "").lower() in ("1", "true", "yes")),
        )

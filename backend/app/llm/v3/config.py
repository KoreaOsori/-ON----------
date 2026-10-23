"""v2 전용 설정.

- 백엔드의 app.core.config 는 건드리지 않고(= v2 밖 수정 금지) 환경변수에서 직접 읽는다.
- DB/임베딩 환경변수 이름은 vector_pipeline 과 동일하게 맞췄다(PGHOST, RDS_SECRET_ARN ...). 리전은 환경변수 없이 us-east-1 로 고정.
- 비밀값(DB 비밀번호)은 repr/로그에 남지 않도록 repr=False 로 둔다.
  RDS_SECRET_ARN 이 있으면 비밀번호는 여기에 저장하지 않고 연결을 만들 때마다 Secrets Manager 에서 읽는다.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    """설정 누락/오류. 메시지에는 비밀값을 넣지 않는다."""


# vector_pipeline 의 EmbeddingConfig 와 같은 값이어야 DB(pipeline_config)와 일치한다.
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
SCHEMA_VERSION = 2

# 리전은 us-east-1 로 고정한다(환경변수로 바꾸지 않는다). 임베딩·Claude·Secrets Manager 모두 이 리전을 쓴다.
REGION = "us-east-1"

# DB 위치(호스트·포트·DB 이름)는 코드에 적지 않고 앱 시크릿(pill-check/dev/app)의 DB_HOST, DB_PORT, DB_NAME 에서 읽는다(db.resolve_endpoint).
# 시크릿 이름은 비밀값이 아니다(docker-compose.yml 에도 있다). 다른 시크릿을 쓰려면 DB_SECRET_ID 환경변수로 바꾼다(백엔드와 같은 이름).
# PGHOST(또는 DB_HOST)가 있으면 시크릿을 쓰지 않고 환경변수만 쓴다(로컬 개발 DB·SSM 터널 용도).
DEFAULT_APP_SECRET_ID = "pill-check/dev/app"
# 접속 계정(username/password)은 RDS 가 관리하는 이 시크릿에서 연결마다 새로 읽는다(비밀값 아님, 이름뿐).
DEFAULT_DB_SECRET_ID = "rds!db-71cf9992-e13e-4601-88da-425ac219f336"
# RDS 호스트일 때 PGSSLROOTCERT 가 없으면 v2 폴더에 둔 AWS 공식 RDS CA 번들(us-east-1)을 쓴다. v1 의 같은 파일을 복사한 것이라 v1 과 독립적이다.
# CA 가 바뀌면 AWS 공식 번들(https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem)로 갱신한다.
DEFAULT_DB_CA_FILE = str(Path(__file__).resolve().parent / "certs" / "us-east-1-bundle.pem")

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
class V3Settings:
    # --- AWS ---
    region: str = REGION
    embedding_model_id: str = EMBEDDING_MODEL_ID
    embedding_dimensions: int = 1024
    # AWS 자격증명 정책: auto(EC2 위에서는 인스턴스 역할만 허용, 그 밖에는 기본 체인) | ec2_role(항상 엄격) | default_chain(항상 완화)
    auth_mode: str = "auto"

    # --- DB (읽기 전용 연결) ---
    db_host: str | None = None  # None 이면 app_secret_id 시크릿의 DB_HOST 를 연결할 때 읽는다
    db_port: int | None = None  # None 이면 시크릿의 DB_PORT(없으면 5432)
    db_name: str | None = None  # None 이면 시크릿의 DB_NAME
    app_secret_id: str | None = None
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
    # 시스템 프롬프트·도구 정의를 Bedrock 프롬프트 캐시에 올린다(같은 prefix 를 5분 안에 다시 보내면 캐시 읽기 단가로 처리).
    prompt_cache: bool = True
    thinking_disabled: bool = True  # 확장 생각(thinking) 블록을 끈다. 보이지 않는 출력 토큰을 줄인다

    # --- 하니스 한도 ---
    max_tool_rounds: int = 4
    max_tool_calls: int = 6
    max_seconds: float = 60.0
    max_question_chars: int = 500

    # --- 검색 정책 ---
    search_top_k: int = 5
    # 코사인 거리가 이 값보다 큰 근거는 버린다(관련 없는 문단을 모델에 주지 않기 위해). 0~2.
    # 0.80: retrieval_eval --mode calibrate 결과(Titan V2, 샘플 60개)에서 정답 근거 95% 통과, 무관 질문 99% 차단.
    # v1 의 초기값 0.65 는 정답의 약 68% 를 걸러냈다. 데이터·임베딩 모델이 바뀌면 다시 보정해야 한다.
    max_distance: float = 0.80
    # 제품명 없이 전체를 exact 스캔하는 검색. 느릴 수 있어 기본은 끈다.
    allow_global_search: bool = False
    # 병용금기 인덱스(SQLite, contra_index 로 만든 파일) 경로. 비우면 v2/dev_data/contraindication.sqlite 가 있을 때만 켠다.
    contra_db_path: str = ""
    # 병용금기 자료 출처: auto(경로 지정 또는 dev_data 파일이 있으면 SQLite, 없으면 RDS gold.drug_contraindication) | rds | sqlite | off
    contra_source: str = "auto"

    # --- HTTP API (api.py) ---
    # 비우면 키 없이 열린다(localhost 전용으로만 쓸 것). 값이 있으면 X-API-Key 헤더가 일치해야 한다. AWS 키와 무관하다.
    api_key: str = field(default="", repr=False)
    api_max_concurrency: int = 4  # 동시에 처리할 질문 수(DB 풀·Bedrock 호출 보호)
    api_queue_seconds: float = 5.0  # 자리가 날 때까지 기다리는 최대 시간. 넘기면 503

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
    def from_env(cls, env: Mapping[str, str] | None = None) -> "V3Settings":
        original = os.environ if env is None else env
        env = dict(original)
        for key, value in original.items():
            if key.startswith("LLM_V2_"):
                env.setdefault(key.replace("LLM_V2_", "LLM_V3_", 1), value)
        dimensions = _int(env, "EMBEDDING_DIMENSIONS", 1024)
        if dimensions not in (256, 512, 1024):
            raise ConfigError("EMBEDDING_DIMENSIONS 는 256, 512, 1024 중 하나여야 합니다.")
        model = env.get("EMBEDDING_MODEL_ID") or EMBEDDING_MODEL_ID
        if model != EMBEDDING_MODEL_ID:
            raise ConfigError("현재는 Titan Text Embeddings V2 만 지원합니다.")

        provider = (env.get("LLM_V3_PROVIDER") or "bedrock").lower()
        if provider not in ("bedrock", "mantle"):
            raise ConfigError("LLM_V3_PROVIDER 는 bedrock 또는 mantle 이어야 합니다.")

        auth_mode = (env.get("LLM_V3_AUTH_MODE") or "auto").lower()
        if auth_mode not in ("auto", "ec2_role", "default_chain"):
            raise ConfigError("LLM_V3_AUTH_MODE 는 auto, ec2_role, default_chain 중 하나여야 합니다.")

        # PGHOST 가 없으면 앱 시크릿에서 호스트·포트·DB 이름을 읽고(계정은 RDS 시크릿), 있으면 환경변수만 쓴다.
        env_host = _first(env, "PGHOST", "DB_HOST")
        db_host = env_host  # 없으면 연결할 때 시크릿에서
        db_name = _first(env, "PGDATABASE", "DB_NAME")
        app_secret_id = None if env_host else (env.get("DB_SECRET_ID") or DEFAULT_APP_SECRET_ID)
        secret_id = env.get("RDS_SECRET_ARN") or (None if env_host else DEFAULT_DB_SECRET_ID)
        # 호스트를 아직 모르면(시크릿에서 읽을 때) 이 서비스는 RDS 이므로 RDS CA 번들을 쓴다.
        ssl_root_cert = env.get("PGSSLROOTCERT") or (
            DEFAULT_DB_CA_FILE if db_host is None or db_host.endswith(".rds.amazonaws.com") else None
        )

        ssl_mode = env.get("PGSSLMODE") or "verify-full"
        if ssl_mode not in ("verify-full", "require", "disable"):
            raise ConfigError("PGSSLMODE 는 verify-full, require, disable 중 하나여야 합니다.")

        max_distance = _float(env, "LLM_V3_MAX_DISTANCE", 0.80)
        if not 0 <= max_distance <= 2:
            raise ConfigError("LLM_V3_MAX_DISTANCE 는 0 이상 2 이하여야 합니다.")

        default_model = (env.get("LLM_V3_DEFAULT_MODEL") or "haiku").lower()
        if default_model not in ("haiku", "sonnet"):
            raise ConfigError("LLM_V3_DEFAULT_MODEL 은 haiku 또는 sonnet 이어야 합니다.")

        contra_source = (env.get("LLM_V3_CONTRA_SOURCE") or "auto").lower()
        if contra_source not in ("auto", "rds", "sqlite", "off"):
            raise ConfigError("LLM_V3_CONTRA_SOURCE 는 auto, rds, sqlite, off 중 하나여야 합니다.")

        return cls(
            region=REGION,
            embedding_model_id=model,
            embedding_dimensions=dimensions,
            auth_mode=auth_mode,
            db_host=db_host,
            db_port=int(_first(env, "PGPORT", "DB_PORT")) if _first(env, "PGPORT", "DB_PORT") else None,
            db_name=db_name,
            app_secret_id=app_secret_id,
            db_user=_first(env, "PGUSER", "DB_USERNAME"),
            db_password=_first(env, "PGPASSWORD", "DB_PASSWORD"),
            rds_secret_arn=secret_id,
            db_ssl_mode=ssl_mode,
            db_ssl_root_cert=ssl_root_cert,
            db_statement_timeout_ms=_int(env, "LLM_V3_DB_STATEMENT_TIMEOUT_MS", 15000),
            db_pool_size=_int(env, "LLM_V3_DB_POOL_SIZE", 3),
            llm_provider=provider,
            haiku_model_id=env.get("LLM_V3_HAIKU_MODEL_ID") or DEFAULT_HAIKU_MODEL_ID,
            sonnet_model_id=env.get("LLM_V3_SONNET_MODEL_ID") or DEFAULT_SONNET_MODEL_ID,
            default_model=default_model,
            llm_model_id=env.get("LLM_V3_MODEL_ID") or None,
            llm_max_tokens=_int(env, "LLM_V3_MAX_TOKENS", 2000),
            prompt_cache=(env.get("LLM_V3_PROMPT_CACHE", "1").lower() not in ("0", "false", "no", "off")),
            thinking_disabled=(env.get("LLM_V3_THINKING", "off").lower() in ("0", "false", "no", "off", "disabled")),
            max_tool_rounds=_int(env, "LLM_V3_MAX_TOOL_ROUNDS", 4),
            max_tool_calls=_int(env, "LLM_V3_MAX_TOOL_CALLS", 6),
            max_seconds=_float(env, "LLM_V3_MAX_SECONDS", 60.0),
            search_top_k=_int(env, "LLM_V3_SEARCH_TOP_K", 5),
            max_distance=max_distance,
            allow_global_search=(env.get("LLM_V3_ALLOW_GLOBAL_SEARCH", "").lower() in ("1", "true", "yes")),
            contra_db_path=env.get("LLM_V3_CONTRA_DB") or "",
            contra_source=contra_source,
            api_key=env.get("LLM_V3_API_KEY") or "",
            api_max_concurrency=max(1, _int(env, "LLM_V3_API_MAX_CONCURRENCY", 4)),
            api_queue_seconds=max(0.0, _float(env, "LLM_V3_API_QUEUE_SECONDS", 5.0)),
        )

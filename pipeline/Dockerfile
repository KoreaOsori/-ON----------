# syntax=docker/dockerfile:1.7
# ---- 데이터 파이프라인 (API → S3 bronze → S3 silver → S3 gold → RDS) ----
# 항상 띄우지 않고 필요할 때만 실행하는 일회성 컨테이너. deploy/ec2/docker-compose.yml 의 data-pipeline 서비스로 실행한다.
# 데이터는 S3 에 읽고 쓴다. 빌드 중 임시 파일은 컨테이너 안 임시 폴더(/tmp)에 쓰고 끝나면 지운다.
FROM python:3.12-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project --no-dev

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app/pipeline
COPY . .
ENTRYPOINT ["python", "run_pipeline.py"]

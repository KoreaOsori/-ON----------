#!/usr/bin/env bash
# S3 모델 버킷 models/{cnn,ocr_models,rx}/ → ./deploy (EC2 에서 실행, plan.md 5-4)
# 버킷 이름은 .env 의 MODEL_BUCKET 에서 읽는다 (코드에 쓰지 않음). 인증은 EC2 IAM 역할 (models/* 읽기만 허용)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
: "${MODEL_BUCKET:?.env 에 MODEL_BUCKET 을 넣어 주세요 (terraform output model_bucket)}"

aws s3 sync "s3://${MODEL_BUCKET}/models/" ./deploy/ --exclude "*/.cache/*" --only-show-errors
echo "deploy/ 파일 수: $(find deploy -type f | wc -l)  (PC 업로드 기준 19개)"
du -sh deploy/*

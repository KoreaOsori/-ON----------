#!/bin/bash
# LocalStack 준비 완료 시 실행: 로컬 업로드 버킷 + 브라우저 직접 업로드용 CORS 설정
set -euo pipefail

BUCKET=yakon-local-uploads

awslocal s3api create-bucket \
  --bucket "$BUCKET" \
  --create-bucket-configuration LocationConstraint=ap-northeast-2 || true

awslocal s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration '{
  "CORSRules": [{
    "AllowedOrigins": ["http://localhost:3000"],
    "AllowedMethods": ["PUT", "GET"],
    "AllowedHeaders": ["*"],
    "MaxAgeSeconds": 3000
  }]
}'

echo "S3 bucket ready: $BUCKET"

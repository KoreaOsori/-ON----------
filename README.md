# 약온 (약 정보 서비스)

> 일상에 안심을 더하다 — 챗봇 기반 약 정보 · 병용 확인 · 주변 약국 · 복약 관리 서비스

| 영역 | 기술 |
| --- | --- |
| Frontend | Next.js 16 (App Router), React 19, Tailwind CSS v4, TypeScript, pnpm |
| Backend | FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL, Redis, uv |
| AI | Amazon Bedrock — Claude (`anthropic[bedrock]` Mantle 클라이언트) |
| Infra | AWS ECS Fargate · ALB · RDS PostgreSQL · ElastiCache Redis · S3 · ECR · Secrets Manager, Terraform |

## 디렉터리 구조

```
.
├── frontend/                 # Next.js
│   └── src/
│       ├── app/              # 라우트 (page.tsx = 챗봇, (service)/medicine|pharmacy|mypage)
│       ├── features/<기능>/   # 기능 단위: components/, hooks/, api.ts, types.ts
│       ├── components/       # 공용 UI(ui/), 레이아웃(layout/)
│       ├── providers/        # 전역 상태 (SessionProvider)
│       ├── lib/              # 상수, API 클라이언트
│       ├── mocks/            # 화면용 가상 데이터 (API 연동 시 교체)
│       └── types/
├── backend/                  # FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── core/             # 설정, JWT, 공용 스키마
│   │   ├── db/               # 엔진/세션, Base, 모델 등록
│   │   ├── integrations/     # Bedrock, S3/Textract, Redis, 공공데이터 API
│   │   └── modules/<도메인>/  # router · schemas · service · models
│   │       # auth, users, chat, medicines, interactions, pharmacies, medications, uploads, ocr, health
│   ├── alembic/              # DB 마이그레이션
│   └── tests/
├── infra/
│   ├── local/localstack/     # 로컬 S3 버킷 초기화 스크립트
│   └── terraform/
│       ├── bootstrap/        # 원격 state 버킷 (최초 1회)
│       ├── modules/          # network, security, ecr, s3, rds, redis, alb, ecs, secrets
│       └── envs/dev/         # dev 환경 조합
└── docker-compose.yml        # 로컬 개발 환경
```

## 로컬 개발

### 사전 준비
- Docker Desktop, Node.js 22+, pnpm 10, Python 3.12, [uv](https://docs.astral.sh/uv/)

### 1. 환경변수
```bash
cp backend/.env.example backend/.env          # JWT_SECRET_KEY 는 임의의 긴 문자열로 변경
cp frontend/.env.example frontend/.env.local
```

### 2. 전체 실행 (Docker Compose)
```bash
docker compose up -d --build   # postgres · redis · localstack(S3) · backend · frontend
```

| 서비스 | 호스트 주소 |
| --- | --- |
| PostgreSQL | `localhost:5555` (user/pw/db: `yakon`) — 호스트 5432 충돌을 피하려고 5555 사용, `POSTGRES_HOST_PORT` 로 변경 가능 |
| Redis | `localhost:6379` |
| S3 (LocalStack) | `http://localhost:4566`, 버킷 `yakon-local-uploads` |
| Backend API | http://localhost:8000/api/v1 — 문서: http://localhost:8000/api/v1/docs |
| Frontend | http://localhost:3321 (`FRONTEND_HOST_PORT` 로 변경 가능) |

- 백엔드 컨테이너는 시작 시 `alembic upgrade head` 를 실행하고, `backend/app` 을 마운트해 코드 변경 시 자동으로 재시작합니다.
- 프론트 컨테이너는 `frontend/` 소스를 마운트해 `next dev` 로 실행합니다. Windows 바인드 마운트에서는 Turbopack 이 파일 변경을 감지하지 못해 webpack + 폴링(1초)을 사용하며, 저장 후 몇 초 안에 반영됩니다.
- `package.json` 의존성을 바꾼 뒤에는 `docker compose up -d --build -V frontend` 로 다시 빌드합니다. `-V` 를 붙여야 이전 `node_modules` 볼륨이 교체됩니다.

### 3. 프론트엔드를 컨테이너 없이 실행할 때
```bash
docker compose stop frontend
cd frontend
pnpm install
pnpm dev        # http://localhost:3000 (Turbopack)
```

### 백엔드를 컨테이너 없이 실행할 때
```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### 자주 쓰는 명령
```bash
# Backend
uv run pytest
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "설명"   # 모델 변경 후 마이그레이션 생성
uv run alembic upgrade head

# Frontend
pnpm lint && pnpm typecheck && pnpm build
```

로컬에서는 `DEMO_LOGIN_ENABLED=true` 일 때 `POST /api/v1/auth/demo-login` 으로 데모 토큰을 받을 수 있습니다.

## 주요 설정 (backend/.env)

| 변수 | 설명 |
| --- | --- |
| `BEDROCK_ENABLED` | `false` 면 챗봇이 목업 응답. Bedrock 모델 접근 권한 확인 후 `true` |
| `BEDROCK_MODEL_ID` / `BEDROCK_FALLBACK_MODEL_ID` | 기본 `anthropic.claude-opus-5-5` / 거절 시 `anthropic.claude-opus-4-8` 로 재시도 |
| `OCR_PROVIDER` | `mock` \| `claude`(권장) \| `textract` — Textract 는 한국어 미지원 |
| `DRUG_DATA_SOURCE` | `mock` \| `public_api`(식약처 e약은요, `PUBLIC_DATA_SERVICE_KEY` 필요) |
| `GUEST_DAILY_QUESTION_LIMIT` | 비회원 일일 질문 수 (기본 8) |

## AWS 배포 (dev)

### 아키텍처
```
Internet → ALB ─┬─ /api/*  → ECS backend (FastAPI :8000) ─┬─ RDS PostgreSQL
                └─ 그 외    → ECS frontend (Next.js :3000)  ├─ ElastiCache Redis (TLS)
                                                          ├─ S3 업로드 버킷 (presigned URL)
                                                          └─ Bedrock (Claude)
```
ECS 태스크·RDS·Redis 는 프라이빗 서브넷에 두고, 비밀값은 Secrets Manager 에서 주입합니다.

### 1. 원격 state 버킷 생성 (최초 1회)
```bash
cd infra/terraform/bootstrap
terraform init && terraform apply
# 출력된 state_bucket 이름을 기록
```

### 2. dev 환경 생성
```bash
cd infra/terraform/envs/dev
cp backend.hcl.example backend.hcl            # bucket = <state_bucket>
cp terraform.tfvars.example terraform.tfvars
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```
처음 apply 할 때는 ECR 에 이미지가 없어 ECS 태스크가 시작되지 않습니다. 아래 3단계로 이미지를 올리면 정상화됩니다.

### 3. 이미지 빌드 · ECR 푸시
```bash
REGION=ap-northeast-2
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
TAG=latest   # 운영에서는 git SHA 권장 (terraform 변수 image_tag 와 일치시킬 것)

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REGISTRY

docker build --platform linux/amd64 --target runtime -t $REGISTRY/yakon/backend:$TAG backend
docker build --platform linux/amd64 -t $REGISTRY/yakon/frontend:$TAG frontend   # NEXT_PUBLIC_API_BASE_URL 비움 = 같은 도메인 /api
docker push $REGISTRY/yakon/backend:$TAG
docker push $REGISTRY/yakon/frontend:$TAG

aws ecs update-service --cluster yakon-dev-cluster --service yakon-dev-backend  --force-new-deployment
aws ecs update-service --cluster yakon-dev-cluster --service yakon-dev-frontend --force-new-deployment
```

### 4. 비밀값 채우기
`terraform output app_secret_arn` 시크릿에 OAuth 클라이언트 ID/Secret, `PUBLIC_DATA_SERVICE_KEY` 를 입력합니다. (JWT 키는 자동 생성, DB 비밀번호는 RDS 가 관리)

## 알아둘 점

- **처방전 OCR**: AWS Textract 는 한국어를 지원하지 않습니다. 한국어 처방전에는 `OCR_PROVIDER=claude`(Bedrock Claude 이미지 인식)를 권장합니다.
- **Bedrock 리전**: 서울(ap-northeast-2)은 Claude in Bedrock 의 **Global 엔드포인트만** 지원하므로, 요청이 다른 리전에서 처리될 수 있습니다. 건강정보(민감정보)를 다루므로 개인정보 처리방침에 국외 이전/처리 고지가 필요한지 검토하세요.
- **Structured outputs**: Bedrock(Mantle) 엔드포인트는 `output_config.format` 을 지원하지 않아, OCR 결과는 프롬프트로 JSON 을 요청한 뒤 방어적으로 파싱합니다.
- **모델 접근 권한**: Claude Opus 5.5 는 Bedrock 콘솔에서 계정별 접근 조건을 확인해야 합니다. IAM 액션은 `bedrock-mantle:CreateInference` 입니다.
- **비회원 건강정보 문구**: 백엔드와 연동하면 임시 건강정보가 요청 본문으로 서버에 전송됩니다(저장은 안 함). `GuestProfileModal` 의 "서버에 전송하지 않아요" 문구를 연동 시 수정하세요.
- 현재 프론트엔드 화면은 `src/mocks` 의 가상 데이터로 동작하며, 각 기능의 `api.ts` 에 백엔드 호출 함수가 준비되어 있습니다.

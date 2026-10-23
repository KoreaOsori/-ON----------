# pill_model 실행 계획 (Claude Code용)

> 규칙은 `CLAUDE.md`. 이 문서는 **순서·설계·체크포인트**. 🔒 표시는 사용자 승인 후에만 실행.
> 기준 저장소: KoreaOsori/-ON---------- main (#36, 2026-10-22). 팀 코드 사실관계는 이 시점에 읽고 확인한 것.

---

## 0. 사전 준비 (사용자)

### 0-1. PC에 설치
| 도구 | 용도 | 확인 명령 |
|---|---|---|
| AWS CLI v2 | 자격 증명, S3 업로드 | `aws --version` |
| Session Manager 플러그인 | EC2 접속(SSM) | `session-manager-plugin --version` |
| Terraform ≥ 1.10 | 별도 스택 (팀과 같은 버전 조건) | `terraform version` |
| Git | push/pull | `git --version` |
| (선택) Docker Desktop | PC에서 워커 이미지 테스트 | `docker version` |

### 0-2. AWS 자격 증명 (교육 계정 `de-ai-21`)
```bash
aws configure                      # Access Key / Secret / region=us-east-1
aws sts get-caller-identity        # 계정·사용자 확인 (출력은 공유하지 말 것)
aws iam list-attached-user-policies --user-name de-ai-21   # 붙은 정책 확인
aws s3 ls                          # 팀 state 버킷(…tfstate…)·데이터 버킷 이름 확인
```
콘솔에서 확인해 `terraform.tfvars`에 넣을 값 (2-1 참고): **백엔드 인스턴스의 VPC ID, 퍼블릭 서브넷 ID, 보안 그룹 ID**.
⚠ 콘솔에서 만들던 EC2·SG가 있으면 생성 취소(이미 만들었다면 종료) — 이 스택이 만든다.
필요 권한 (부족하면 계정 관리자에게 요청):
- **EC2**: RunInstances, TerminateInstances, Start/StopInstances, Describe*, CreateTags, ModifyInstanceAttribute,
  Create/DeleteSecurityGroup, Authorize/RevokeSecurityGroupIngress·Egress
- **IAM** (⚠ PowerUserAccess에는 없음): Create/Delete/GetRole, Put/Delete/GetRolePolicy, Attach/DetachRolePolicy,
  ListRolePolicies, ListAttachedRolePolicies, TagRole, Create/Delete/GetInstanceProfile,
  Add/RemoveRoleToInstanceProfile, ListInstanceProfilesForRole, **PassRole**
- **S3**: CreateBucket, DeleteBucket, ListBucket, Put/GetBucket{PublicAccessBlock, Encryption, Versioning, Policy, Tagging, OwnershipControls},
  모델 버킷 객체 Put/Get, **팀 state 버킷의 `pill-check/dev/pill-model.tfstate*` 객체 Get/Put/Delete**
- **SSM**: GetParameter(AMI 조회), StartSession, TerminateSession · **STS**: GetCallerIdentity
- IAM 권한이 막혀 있으면 → 진행하지 말고 사용자에게 보고(대안: 관리자가 역할을 만들어 주고 이름만 받기).

### 0-3. Colab에서 버전 확인 (재현성)
```python
!python --version
!pip freeze | grep -iE "^(paddle|paddleocr|paddlex|torch|timm|rapidfuzz|opencv|numpy|pandas|scipy|pillow)"
```
→ 출력을 `pill_model/requirements.lock.txt` 근거로 사용(torch는 CPU 빌드로). Colab과 버전이 다르면 결과가 달라질 수 있음.

### 0-4. 파일 준비
- Drive `pill_project/cnn/deploy/` 전체(cnn_v5.pt, gallery_v5.npy, gallery_index.csv, pill_db.csv, config.json, yakon_pill.py)를 PC로 내려받기.
- `yakon_pill.py` → `pill_model/app/yakon_pill.py` 로 **그대로** 복사 (수정 금지).
- 대조용 평가 사진 3~5쌍(RGBA)과 Colab에서 같은 사진으로 돌린 `analyze` 결과 JSON을 `pill_model/tests/fixtures/`에 (사진은 gitignore, JSON만 커밋 가능).

---

## 0-5. 처방전·약봉투 OCR 추가 (2026-10-23 결정: 같은 워커에 `/rx/*`)
- 프런트가 사진 종류를 나눔: 처방전·약봉투 → `/rx/analyze` / 알약 → `/pill/analyze`.
- 코드: `app/rx/yakon_rx.py` (노트북 R-2a·2b·2c v4·2f·2g·2h v3·B-ALL을 옮긴 모듈, **수정 금지** — Colab R-E2로 노트북 결과와 동일함을 검증한 파일).
- 데이터: `deploy/rx/` = `config_rx.json`, `permit_names.csv`, `dose_envelope.json` (Colab R-E1 산출물).
- OCR 모델 공용: `deploy/ocr_models/paddleocr_v5_korean_2026-10-14/` (PP-OCRv5_server_det, korean_PP-OCRv5_mobile_rec).
  컨테이너에서 PaddleOCR 캐시 위치(`~/.paddlex/official_models/`)에 연결해 인터넷 다운로드 없이 쓰는지 확인할 것.
- **버전 고정 (Colab CPU 실측 환경)**: Python **3.13**, paddlepaddle **3.2.2** (⚠ 3.3.x CPU는 oneDNN 버그 — 노트북 기록),
  paddleocr **3.7.0**, paddlex **3.7.2**. 알약 각인 OCR(E-6)도 같은 CPU v2 설치 셀을 썼음.
- OCR 엔진 1개 공유: 알약 설정(검출 640)으로 생성 → 처방전은 호출마다 1280(`per_call_limit`). Colab R-E3 ②가 ✅일 때만.
  ❌이면 엔진 2개(메모리 측정 후 사용자에게 보고).
- LLM: Bedrock Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`, us-east-1) — 🔒 워커 IAM 역할에 `bedrock:InvokeModel`
  (해당 추론 프로필·기반 모델 ARN) 추가 필요 → Terraform plan → 사용자 apply. Colab의 Bearer 키는 서버에서 쓰지 않음.
- 개인정보: 처방전 사진·OCR 글자·LLM 입출력은 **저장·로그 금지**. 로그에는 장 수·시간·약 개수·판정 종류만.
- API (워커 내부):
  | `POST /rx/analyze` | key(purpose=`prescription`) | doc_type, drugs[이름 판정·후보·숫자 3개(value·ui)], privacy(차단 줄 수), timing, notice |
  | `POST /rx/confirm` | sessionId, drug index, itemSeq | 그 약의 숫자 ui에 용법 상한 검증 반영(over·reason) |
- IAM: 업로드 버킷 읽기 경로에 `prescription/*` 추가 필요(현재 `pill/*`만).

## 1. 폴더 구조 (만들 것)
```
pill_model/
├── CLAUDE.md  PLAN.md  README.md
├── .gitignore  .dockerignore  .env.example
├── Dockerfile  compose.yaml  requirements.txt
├── deploy/            # (gitignore) S3 models/ 와 같은 구조
│   ├── ocr_models/paddleocr_v5_korean_2026-10-14/   # 공용 OCR 모델
│   ├── cnn/           # cnn_v5.pt · gallery_v5.npy · gallery_index.csv · pill_db.csv · config.json
│   └── rx/            # config_rx.json · permit_names.csv · dose_envelope.json
├── app/
│   ├── main.py        # FastAPI: 라우트, 시작 시 모델 적재, 동시성 1 (/pill/* · /rx/* 공용)
│   ├── ocr_engine.py  # PaddleOCR 1개 생성 → 알약·처방전 공유
│   ├── pill/yakon_pill.py  # Colab 검증 모듈 (복사본, 수정 금지) — PillIdentifier(deploy/cnn, load_ocr=False) 후 .ocr 주입
│   ├── rx/yakon_rx.py      # Colab 검증 모듈 (복사본, 수정 금지) — RxReader(deploy/rx, ocr=공유 엔진)
│   ├── schemas.py     # 요청·응답 Pydantic 모델 (camelCase 응답은 백엔드와 맞춤)
│   ├── sessions.py    # 세션 보관(메모리, TTL 10분)
│   ├── storage.py     # S3: 업로드 사진 읽기, 동의한 crop 저장, 모델 내려받기
│   ├── images.py      # silver pill_identification → item_seq: image_url
│   └── bg.py          # rembg 배경 제거 (모델 이름은 환경변수)
├── scripts/
│   ├── fetch_models.sh   # S3 models/v5/ → ./deploy (EC2에서)
│   └── bench.py          # 속도·대조 측정 (fixtures 사용)
├── tests/                # pytest: 스키마, 세션 TTL, image_url 결합, 대조 테스트
├── docs/devlog.md        # 개발 기록
└── infra/terraform/
    ├── versions.tf  main.tf  variables.tf  outputs.tf  user_data.sh
    ├── backend.hcl.example  terraform.tfvars.example
```
`pill_model/.gitignore` (루트 .gitignore는 수정하지 않음):
```
deploy/
crops/
*.pt
*.npy
*.parquet
*.onnx
tests/fixtures/*.png
tests/fixtures/*.jpg
.env
infra/terraform/.terraform/
infra/terraform/*.tfstate*
infra/terraform/terraform.tfvars
infra/terraform/backend.hcl
```

---

## 2. Terraform 별도 스택 (`pill_model/infra/terraform`)

### 2-1. 팀 자원 — 읽기만 (`data`, **ID는 변수로 받는다**)
⚠ 실제 교육 계정의 자원 이름(`agent-de-ai-01-*`)이 저장소 팀 Terraform의 이름 규칙(`pill-check-dev-*`)과 다르다(2026-10-22 콘솔 확인).
→ 이름 태그로 찾지 말고, 사용자가 콘솔에서 확인한 **ID를 `terraform.tfvars`(gitignore)로 받아** `data` 블록에서 존재만 검증한다.

| 변수 (`variables.tf`, 기본값 없음) | 콘솔에서 확인한 값 (예시 — 실제 값은 tfvars에만) | 검증용 data |
|---|---|---|
| `vpc_id` | `agent-de-ai-01-vpc`의 ID | `aws_vpc` id |
| `subnet_id` | 백엔드와 같은 VPC의 **퍼블릭** 서브넷 (예: `agent-de-ai-01-public-*`) | `aws_subnet` id → vpc_id 일치 검사(`precondition`) |
| `backend_sg_id` | 백엔드 EC2에 붙은 SG (예: `agent-de-ai-01-ec2-sg`) — **백엔드 인스턴스 화면에서 확인** | `aws_security_group` id → vpc_id 일치 검사 |
| `data_bucket_name` | silver가 있는 데이터 버킷 (`aws s3 ls`로 확인) | `aws_s3_bucket` |
| `upload_bucket_name` | 운영 업로드 버킷 (hesouu 확인 전엔 `""`) | 빈 값이면 생략 |
| AMI | 변수 아님 — `aws_ssm_parameter` `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` | |

- `terraform.tfvars.example`에는 **자리표시자만**(`vpc-xxxxxxxx`) 넣는다. 실제 ID는 커밋 금지.
- 이름 접두어는 변수 `name_prefix`(기본 `pill-worker`)로 새 자원에 붙인다.
- state 버킷도 계정마다 다를 수 있음 → `aws s3 ls`에서 확인. **팀 state 버킷이 없으면** 진행 멈추고 사용자에게 질문
  (대안: 이 스택 전용 state 버킷을 콘솔로 1개 만들기 — 사용자 승인 후).
- plan 전에 위 값들이 실제로 조회되는지 `aws ec2 describe-vpcs/describe-subnets/describe-security-groups --*-ids <id>`로 먼저 확인(조회라 승인 불필요).

### 2-2. 새로 만드는 자원 (전부 이 스택 소유, `terraform destroy`로 정리 가능)
- **모델 버킷** `${name_prefix}-model-${account_id}`: 퍼블릭 차단, 암호화, BucketOwnerEnforced, HTTPS만 허용 정책.
  경로: `models/v5/…`(모델 파일), `crops/YYYY/MM/DD/<uuid>_{front|back}.png`(동의한 알약 조각).
  `force_destroy = false` (crop 실수 삭제 방지 — destroy 전에 비워야 함을 README에 명시).
- **워커 SG** `${name_prefix}-sg` (새로 생성 — 기존 `agent-de-ai-01-ec2-sg`를 워커에 붙이지 않는다): 인바운드 TCP 8000 ← `referenced_security_group_id = var.backend_sg_id`. 아웃바운드 전체(패키지·S3).
  ⚠ 팀 SG에는 규칙을 추가하지 않는다(백엔드 SG 아웃바운드가 이미 전체 허용임을 확인함).
- **IAM 역할·인스턴스 프로필** `${name_prefix}-role` (생성 권한 없으면 plan/apply 오류 → 멈추고 사용자에게 보고):
  - `AmazonSSMManagedInstanceCore`
  - 모델 버킷: `models/*` Get, `crops/*` Put, ListBucket(prefix models/)
  - 데이터 버킷: `silver/_latest.json`, `silver/pill_identification/*` Get, ListBucket(prefix silver/pill_identification/)
  - 업로드 버킷: `pill/*` Get — 변수 `upload_bucket_name`이 빈 값이면 이 문장 생략 (팀 확인 대기)
- **EC2** `${name_prefix}`: t3.medium, 키 페어 없음(SSM 접속), 퍼블릭 IP 자동 할당, `credit_specification { cpu_credits = "standard" }`,
  gp3 30GB encrypted, `metadata_options { http_tokens = "required", http_put_response_hop_limit = 2 }`
  (⚠ hop limit 2: 이게 1이면 Docker 컨테이너 안에서 IMDSv2로 IAM 역할 자격 증명을 못 받는다),
  `user_data.sh` = docker·git·compose 플러그인 설치, ec2-user를 docker 그룹에, `/opt/pill_model` 준비.
  탄력적 IP 없음 — 백엔드는 **프라이빗 IP**로 호출(정지·시작해도 프라이빗 IP는 유지).
- 태그: `Project=pill-check, Environment=dev, ManagedBy=terraform, Stack=pill-model`.

### 2-3. state
```hcl
# versions.tf
backend "s3" {
  key          = "pill-check/dev/pill-model.tfstate"   # 팀 키(terraform.tfstate)와 다름
  region       = "us-east-1"
  encrypt      = true
  use_lockfile = true
}
# backend.hcl (gitignore): bucket = "<팀 state 버킷 이름>"
```

### 2-4. outputs
`worker_instance_id`, `worker_private_ip`, `worker_connect`(SSM 명령), `model_bucket`, `worker_url = "http://<private_ip>:8000"`

### 2-5. 체크포인트
1. `terraform init -backend-config=backend.hcl` → `terraform validate` → `terraform plan -out=tfplan` (승인 불필요)
2. plan 결과를 사용자에게 요약: **생성 N개 / 변경 0 / 삭제 0** 확인. 팀 자원 ID가 `data`로만 나오는지 확인.
3. 🔒 `terraform apply tfplan` — 사용자가 직접 실행.

---

## 3. 워커 앱 (`pill_model/app`)

### 3-1. 시작 시
1. `deploy/` 모델 확인(없으면 종료하며 `scripts/fetch_models.sh` 안내) → `PillIdentifier(deploy_dir, load_ocr=True)`.
2. silver `_latest.json` → `pill_identification/snapshot=…/data.parquet` 읽어 `{item_seq: item_image}` 사전. 실패해도 서비스는 시작(`image_url=null`), `/health`에 표시.
3. 워밍업: 더미 이미지 1장으로 OCR·CNN 1회(첫 요청 지연 제거).

### 3-2. API (워커 내부용, 백엔드만 호출)
| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /health` | – | status, model_loaded, image_index_size, version(config), load_sec |
| `POST /pill/analyze` | frontKey, backKey, shape, saveCrops(동의 여부) | sessionId, step(next_step 결과), band, imprintMatch, candidates[+imageUrl], quality, timingSec, caution, storageNotice |
| `POST /pill/reject` | sessionId, fromStep, attempt | 다음 단계(on_reject) |
| `POST /pill/imprint-choice` | sessionId, choice | ask_color 또는 null |
| `POST /pill/refine` | sessionId, imprintFront?, imprintBack?, color? | Top-3 (refine) |
| `POST /pill/confirm` | sessionId, itemSeq, userQuestion? | handoff(item_seq, name, company, confirmed_by_user) → 백엔드가 LLM/RAG로 넘김 |

- 문장·버튼은 `yakon_pill.MSG/BUTTONS` 그대로 (LLM 사용 안 함).
- **세션**: `analyze(return_prepared=True)`의 `_prepared`를 메모리에 10분 보관(JSON 응답에는 넣지 않음). 만료 → 410.
- **동시성**: uvicorn worker 1개 + `asyncio.Semaphore(1)`. 대기 60초 넘으면 503 `busy`. 무거운 계산은 `run_in_threadpool`.
- **입력 검증**: key는 `pill/` 로 시작, 확장자 jpg/png/webp, 10MB 이하. 사진은 디스크에 쓰지 않고 메모리에서 처리.
- **배경 제거**: 알파 채널이 없으면 `bg.py`(rembg, 세션 재사용)로 제거 → `quality()` 검사.
- **crop 저장**: `saveCrops=true`일 때만, 배경 제거된 RGBA 조각을 `crops/…`에. 원본 사진·사용자 ID는 저장하지 않음.
- **인증**: SG로 백엔드만 접근 + 헤더 `X-Worker-Token`(환경변수, 값은 `.env`·gitignore). 토큰 불일치 401.
- 로그: 요청별 band·timing·결과 단계만. 사진·각인 원문 외 개인정보 없음.

### 3-3. Docker
- 베이스 `python:3.x-slim` (0-3에서 확인한 Colab 버전), torch는 CPU 휠(`--index-url https://download.pytorch.org/whl/cpu`).
- **PaddleOCR 모델과 rembg 모델은 빌드 단계에서 미리 내려받아 이미지에 포함**(실행 중 인터넷 다운로드·HF 토큰 문제 방지 — Colab에서 401 겪음, `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`).
- `compose.yaml`: 포트 `0.0.0.0:8000:8000`(SG가 백엔드만 허용), `./deploy:/app/deploy:ro`, `env_file: .env`, healthcheck `/health`, `restart: unless-stopped`.
- 비루트 사용자로 실행.

### 3-4. 배경 제거 모델 선택 실험 (EC2에서, 승인 불필요 — 로컬 측정)
| 후보 | 근거 |
|---|---|
| `u2netp` | rembg README: "A lightweight version of u2net model." — 가장 빠를 것으로 추정 |
| `isnet-general-use` | "A new pre-trained model for general use cases." |
| `silueta` | "Same as u2net but the size is reduced to 43Mb." |
- 측정: fixtures 사진 → (a) 시간 (b) quality() 통과율 (c) **Colab 평가 결과와 후보 일치율**. 사용자에게 표로 보고 → 사용자가 선택.
- **판단 기준(사용자 확정)**: 배경 제거 포함 요청 1건이 **33초 이상**(현재 약 23초 + 10초 초과)이면 Plan B(브라우저 배경 제거) 검토를 사용자에게 제안. 그 미만이면 워커 유지.
- ⚠ rembg 기본값 `bria-rmbg`는 README 원문 "requires a paid agreement for commercial use" → 사용 금지.

---

## 4. 백엔드 연결 (🔒 팀 코드 — 사용자 승인 후 PR, 최소 변경)
- 새 파일: `backend/app/modules/pill/{__init__,router,schemas,service}.py` — 기존 `modules/ocr` 패턴(CamelModel, `CurrentUser`, `/{user.id}/` 소유 확인) 그대로.
  - `service.py`: `httpx.AsyncClient(base_url=settings.pill_worker_url, timeout=90)` + `X-Worker-Token`.
  - 경로: `POST /api/v1/pill/analyze|reject|imprint-choice|refine|confirm` → 워커로 전달.
- 수정 2곳: `core/config.py`에 `pill_worker_url: str | None = None`, `pill_worker_token: str | None = None` / `api/router.py`에 `pill_router` 추가.
- `httpx`가 backend 의존성에 없으면 추가 여부를 사용자에게 먼저 묻는다(`uv.lock` 변경 → 팀 영향).
- 배포 값: 백엔드 EC2 `deploy/ec2/.env`(gitignore)에 `PILL_WORKER_URL=http://<worker_private_ip>:8000`, `PILL_WORKER_TOKEN=…`.
- nginx `proxy_read_timeout 120s` 이미 있음 → 요청 30초 내외면 변경 불필요(확인만).

---

## 5. 배포 순서
1. (PC) 1~3단계 코드 작성 → `pytest` → (선택) PC Docker로 fixtures 대조 테스트.
2. (PC) 🔒 `terraform apply` (사용자) → outputs 확인.
3. (PC) 🔒 `aws s3 sync <deploy 폴더> s3://<model_bucket>/models/v5/ --exclude "yakon_pill.py"`.
4. (PC) 🔒 `git push` (브랜치 → PR → 머지는 팀 규칙대로).
5. (EC2, SSM) `git clone/pull` → `cd pill_model && bash scripts/fetch_models.sh && cp .env.example .env`(토큰 입력) → `docker compose up -d --build`.
6. (EC2) `curl localhost:8000/health` → `python scripts/bench.py` (속도 5회 평균 + Colab 대조).
7. (백엔드 EC2) 🔒 `.env`에 워커 주소 → `docker compose up -d backend` → 백엔드에서 `curl http://<worker_private_ip>:8000/health`.

## 6. 완료 기준
- [ ] plan: 생성만, 팀 자원 변경·삭제 0
- [ ] `/health` 정상, image_index_size > 0
- [ ] fixtures 대조: 후보 Top-3·band·imprint_match가 Colab과 동일 (다르면 원인 보고)
- [ ] 요청 1건 평균 ≤ 30초 (배경 제거 포함 시간 따로 표기)
- [ ] 백엔드 → 워커 호출 성공, 인터넷에서 8000 접근 불가 확인
- [ ] `git diff`에 계정 번호·버킷 이름·토큰·모델 파일 없음
- [ ] devlog.md 기록

## 7. 아직 열린 항목 (진행 중 막히면 사용자에게 질문)
- 운영 업로드 버킷 이름 (hesouu 확인 중) → `upload_bucket_name` 변수
- 배경 제거 모델 (3-4 실험 후 사용자 선택)
- crop 저장 동의 UI 문구 위치 (프런트 팀)

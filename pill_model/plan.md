# pill_model 실행 계획 (Claude Code용)

> 규칙은 `claude.md`. 이 문서는 **순서·설계·체크포인트**. 🔒 표시는 사용자 승인 후에만 실행.
> 기준 저장소: KoreaOsori/-ON---------- main (#36, 2026-10-22). 팀 코드·AWS 사실관계는 이 시점에 읽고 조회한 것.
> 2026-10-23: 처방전 OCR 추가 반영본(사용자)과 PC 정정(silver 경로·업로드 버킷·계정 자원 이름)을 합침.

---

## 0. 사전 준비 (사용자) — ✅ 완료

### 0-1. PC 도구 (2026-10-22 확인)
aws-cli 2.36.7 · session-manager-plugin 1.2.835.0 · Terraform 1.15.8 · Git 2.55 · Docker Desktop (Compose v5.5.1 — EC2는 v2.29.7, compose.yaml은 공통 문법만)

### 0-2. AWS (교육 계정 `de-ai-21`)
- 그룹 정책 `DE-AI-Resource-Isolation-Policy`: `ec2:* / s3:* / iam:* / ssm:* / bedrock:*` 등, 허용 리전에 us-east-1·us-east-2·us-west-2 포함.
- `aws sts get-caller-identity` 출력·계정 번호는 공유·커밋하지 않는다.

### 0-3. 버전 (Colab CPU 실측 환경) → 3-3 constraints 의 근거
| 패키지 | 버전 | 출처 |
|---|---|---|
| Python | 3.13.16 | Colab |
| paddlepaddle | **3.2.2** (CPU, 3.3.x는 oneDNN 버그로 금지) | OCR 노트북 |
| paddleocr / paddlex | 3.7.0 / 3.7.2 | OCR 노트북 |
| opencv-contrib-python | **4.10.0.84 하나만** (paddlex 3.7.2 가 이 버전으로 고정) | OCR·CNN 노트북 확인 셀 |
| torch / torchvision | 2.11.0+cpu / 0.26.0+cpu | CNN 노트북 |
| timm | 1.0.30 | CNN |
| numpy / pandas / pillow / scipy / pyarrow | 2.1.3 / 2.2.3 / 11.3.0 / 1.16.3 / 23.0.1 | Colab |
| rapidfuzz / boto3 | 3.14.6 / 1.43.118 | OCR 노트북 |
| rembg | 2.0.69 (`--no-deps`) | 노트북에서 안 씀 → 3-3·3-4에서 결정·검증 |

opencv 확인 결과(사용자, 2026-10-23): Colab에는 contrib 4.10.0.84·python 5.0.0.93·headless 5.0.0.93 세 개가 같이 깔려 있었으나 실제 `cv2.__version__ = 4.10.0`.
CNN 노트북은 원래 4.14.0 → contrib 4.10.0.84만 남기고 재실행해 알약 6장 OCR 글자가 최종 평가(v1_det640)와 동일 확인. **알약 fixture는 4.10 환경에서 생성.**

### 0-4. 파일 (✅ PC에 있음, `deploy/`는 gitignore)
- `deploy/cnn/`: cnn_v5.pt · gallery_v5.npy · gallery_index.csv · pill_db.csv · config.json
- `deploy/ocr_models/paddleocr_v5_korean_2026-10-14/`: PP-OCRv5_server_det · korean_PP-OCRv5_mobile_rec · MODEL_CARD.json
  (Drive 10/14 보관본과 새로 받은 모델 본체 30개 파일 동일 — 사용자 확인. `.cache/huggingface/` 는 다운로드 기록이라 제외)
  ⚠ MODEL_CARD.json 의 `"paddlepaddle": "3.3.0"` 은 GPU 환경 값 — 버전 기준은 0-3 표.
- `deploy/rx/`: config_rx.json · permit_names.csv(42,714품목, bronze 10/04) · dose_envelope.json(33,921품목)
  - `config_rx.json` 은 `per_call_limit` 만 false → **true** 로 변경 (사용자 승인 2026-10-23).
    원본 sha256 `3ea98dd70d47a60e83ecc307c3eca2cbf2f215ad197f34478c576dd77c78c21b` → 변경 후 `73251b1fa6b8ea5923fd8cfe1de55709dc6196ed6a5cf642181ec7adb625fb56`
- `app/pill/yakon_pill.py`, `app/rx/yakon_rx.py`: Colab 검증본 (수정 금지)
- `tests/fixtures/pill/*.expected.json`(3쌍), `tests/fixtures/rx/*.expected.json`(3장): 커밋 가능 (OCR 원문 없음). 사진은 같은 폴더, gitignore.

---

## 0-5. 처방전·약봉투 OCR (2026-10-23 결정: 같은 워커에 `/rx/*`)
- 프런트가 사진 종류를 나눔: 처방전·약봉투 → `/rx/analyze` / 알약 → `/pill/analyze`.
- 코드: `app/rx/yakon_rx.py` (노트북 R-2a·2b·2c v4·2f·2g A+C·2h v3·B-ALL, **수정 금지** — Colab R-E2에서 노트북과 다른 행 0).
- `RxReader(deploy/rx, ocr=공유 엔진, llm_client=boto3 bedrock-runtime)` — 둘 다 밖에서 주입 가능(코드 확인).
- OCR 엔진 1개 공유: 알약 설정(640)으로 생성 → 처방전은 `predict(..., text_det_limit_side_len=1280)`.
  Colab R-E3 ②: 640 엔진 + 호출별 1280 = 1280 엔진과 글자·확신도까지 동일 → `per_call_limit: true`.
- LLM: Bedrock Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`, us-east-1, Converse). 🔒 워커 IAM에 `bedrock:InvokeModel` (2-2).
- 개인정보: 처방전 사진·OCR 글자·LLM 입출력은 **저장·로그 금지**. 로그에는 장 수·시간·약 개수·판정 종류만.
- Colab 측정: 처방전 1장 17~33초 (OCR 13~33초 + LLM 2~3.5초), 편차 큼 → EC2에서 5회 평균.

---

## 1. 폴더 구조
```
pill_model/
├── claude.md  plan.md  README.md
├── .gitignore  .dockerignore  .env.example
├── Dockerfile  compose.yaml  requirements.txt  constraints.txt
├── deploy/            # (gitignore) S3 models/ 와 같은 구조
│   ├── ocr_models/paddleocr_v5_korean_2026-10-14/   # 공용 OCR 모델
│   ├── cnn/           # cnn_v5.pt · gallery_v5.npy · gallery_index.csv · pill_db.csv · config.json
│   └── rx/            # config_rx.json · permit_names.csv · dose_envelope.json
├── app/
│   ├── main.py        # FastAPI: 라우트, 시작 시 모델 적재, 동시성 1 (/pill/* · /rx/* 공용)
│   ├── ocr_engine.py  # PaddleOCR 1개 생성(yakon_pill._make_ocr 와 같은 인자) → 알약·처방전 공유
│   ├── pill/yakon_pill.py  # 수정 금지 — PillIdentifier(deploy/cnn, load_ocr=False) 후 .ocr 주입
│   ├── rx/yakon_rx.py      # 수정 금지 — RxReader(deploy/rx, ocr=공유 엔진, llm_client=…)
│   ├── schemas.py     # 요청·응답 Pydantic 모델 (camelCase 응답은 백엔드와 맞춤)
│   ├── sessions.py    # 세션 보관(메모리, TTL 10분)
│   ├── storage.py     # S3: 업로드 사진 읽기, 동의한 crop 저장
│   ├── images.py      # silver drug_product(item_seq·pills 컬럼만) → item_seq: image_url
│   └── bg.py          # rembg 배경 제거 (모델 이름은 환경변수)
├── scripts/
│   ├── fetch_models.sh   # S3 models/{cnn,ocr_models,rx}/ → ./deploy (EC2에서)
│   └── bench.py          # 속도·대조 측정 (fixtures 사용)
├── tests/
│   ├── fixtures/pill/  fixtures/rx/   # *.expected.json (커밋) + 사진 (gitignore)
│   └── test_*.py         # pytest: 스키마, 세션 TTL, image_url 결합, 지문·대조
├── docs/devlog.md
└── infra/terraform/   versions.tf  main.tf  variables.tf  outputs.tf  user_data.sh  *.example
```
`.gitignore` 는 실제 파일(`pill_model/.gitignore`)이 기준. 주의: fixture 사진은 **하위 폴더까지** 막는 `tests/fixtures/**/*.jpg` 형식이어야 함
(10-23 이전 규칙 `tests/fixtures/*.jpg` 는 `pill/`·`rx/` 하위에 적용되지 않았음). 루트 `.gitignore` 의 `docs` 규칙은 `!docs/` 로 해제.

---

## 2. Terraform 별도 스택 (`pill_model/infra/terraform`) — ✅ 1차 apply 완료 (2026-10-22, 13개 생성)

### 2-1. 팀 자원 — 읽기만 (`data`, **ID는 변수로 받는다**)
✅ (2026-10-22 조회로 정정) 약ON 백엔드는 `de-ai-21` 계정의 **`pill-check-dev-ec2`** (VPC `pill-check-dev-vpc`) — 팀 Terraform 이름 규칙과 같다.
`agent-de-ai-01-vpc` 는 인스턴스가 없는 다른 VPC라 쓰지 않는다. 그래도 이름이 아니라 **ID를 `terraform.tfvars`(gitignore)로 받는다.**

| 변수 | 실제로 넣은 자원 (ID·이름은 tfvars에만) | 검증용 data |
|---|---|---|
| `vpc_id` | `pill-check-dev-vpc` | `aws_vpc` |
| `subnet_id` | `pill-check-dev-public-us-east-1a` | `aws_subnet` → vpc 일치·퍼블릭 `precondition` |
| `backend_sg_id` | `pill-check-dev-ec2` SG | `aws_security_group` → vpc 일치 |
| `data_bucket_name` | `pill-check-data-<계정>` | `aws_s3_bucket` |
| `upload_bucket_name` | `pill-check-uploads-<계정>` (팀 Terraform 소유, 10-22 23:43 생성 확인) | `aws_s3_bucket` (빈 값이면 생략) |
| AMI | 변수 아님 — SSM `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` | |

### 2-2. 이 스택이 만드는 자원
- **모델 버킷** `${name_prefix}-model-${account_id}`: 퍼블릭 차단, AES256, BucketOwnerEnforced, HTTPS만.
  경로: `models/{cnn,ocr_models,rx}/…`(= `deploy/` 구조), `crops/YYYY/MM/DD/<uuid>_{front|back}.png`. `force_destroy = false`.
- **워커 SG** `${name_prefix}-sg`: 인바운드 TCP 8000 ← 백엔드 SG만. 아웃바운드 전체. 팀 SG에는 규칙 추가 안 함.
- **IAM 역할·인스턴스 프로필** `${name_prefix}-role`:
  - `AmazonSSMManagedInstanceCore`
  - 모델 버킷: `models/*` Get, `crops/*` Put, ListBucket(prefix `models/`)
  - 데이터 버킷: `silver/_latest.json`, `silver/drug_product/*` Get, ListBucket(prefix `silver/drug_product/`)
    (낱알식별은 drug_product 의 `pills` 안에 있음 — 인프라 담당 확인. bronze 권한은 안 넣음)
  - 업로드 버킷: `pill/*` Get · **`prescription/*` Get** (처방전 추가)
  - **Bedrock**: `bedrock:InvokeModel` — 추론 프로필 ARN(us-east-1, 계정) + 기반 모델 ARN 3개(us-east-1·us-east-2·us-west-2).
    조회(10-23): 프로필 `ACTIVE`, 계정 `AUTHORIZED`. 첫 호출에서 AccessDenied 여부 확인.
- **EC2** `${name_prefix}`: t3.medium, credit standard, 키 페어 없음, 퍼블릭 IP, gp3 30GB 암호화, IMDSv2 hop limit 2,
  `user_data.sh` = docker·git·compose v2.29.7·buildx v0.17.1, `/opt/pill_model`. 백엔드는 **프라이빗 IP**로 호출.
- 태그: `Project=pill-check, Environment=dev, ManagedBy=terraform, Stack=pill-model`.

### 2-3. state — `key = "pill-check/dev/pill-model.tfstate"`, `use_lockfile = true`, bucket 은 `backend.hcl`(gitignore)

### 2-4. outputs — `worker_instance_id`, `worker_private_ip`, `worker_connect`, `model_bucket`, `worker_url`

### 2-5. 체크포인트
1. `init` → `validate` → `plan -out=tfplan` (승인 불필요) → 결과(생성/변경/삭제 수, 바뀌는 문장)를 사용자에게 보여줌
2. 🔒 `terraform apply tfplan` — 사용자가 직접 실행

---

## 3. 워커 앱 (`pill_model/app`)

### 3-1. 시작 시
1. `deploy/` 확인(없으면 종료하며 `scripts/fetch_models.sh` 안내).
2. OCR 엔진 1개 생성(`ocr_engine.py`, 알약 설정 640). 실행 로그에 **"Using cached files"** 가 나오는지 확인.
3. `PillIdentifier("deploy/cnn", load_ocr=False)` → `.ocr = 엔진` / `RxReader("deploy/rx", ocr=엔진, llm_client=boto3 bedrock-runtime)`.
4. silver `_latest.json` 의 `tables.drug_product` 날짜 → `drug_product/snapshot=…/data.parquet` 에서 **`item_seq`, `pills` 두 컬럼만** S3 범위 읽기
   (파일 전체 370MB를 받지 않음 — t3.medium 4GB) → `{item_seq: pills[0].item_image}`. 실패해도 서비스는 시작(`image_url=null`), `/health`에 표시.
   - 실측(snapshot 10-23): 두 컬럼 약 14.5초 · 메모리 7.7MB / pills 있는 품목 21,690 · 낱알 21,707행 · 2장 이상 10품목 · URL 빈 값 0 · 호스트 `nedrug.mfds.go.kr`
   - 사진 여러 장이면 `image_id` 순 첫 장(파이프라인 정렬). silver에서 빠진 낱알(허가 취소 등 3,756행)은 image_url 없음.
5. 워밍업: 더미 이미지로 OCR·CNN 1회.

### 3-2. API (워커 내부용, 백엔드만 호출)
| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /health` | – | status, model_loaded(pill·rx), image_index_size, versions(config), load_sec, cv2 버전 |
| `POST /pill/analyze` | frontKey, backKey, shape, saveCrops | sessionId, step, band, imprintMatch, candidates[+imageUrl], quality, timingSec, caution, storageNotice |
| `POST /pill/reject` | sessionId, fromStep, attempt | 다음 단계(on_reject) |
| `POST /pill/imprint-choice` | sessionId, choice | ask_color 또는 null |
| `POST /pill/refine` | sessionId, imprintFront?, imprintBack?, color? | Top-3 (refine) |
| `POST /pill/confirm` | sessionId, itemSeq, userQuestion? | handoff → 백엔드가 LLM/RAG로 넘김 |
| `POST /rx/analyze` | key | sessionId, doc_type, drugs[이름 판정·후보·숫자 3개(value·conf·ui)], privacy, timing, notice, storage |
| `POST /rx/confirm` | sessionId, drugIndex, itemSeq | 그 약의 숫자 ui에 용법 상한 검증 반영(over·reason) |

- 문장·버튼은 `yakon_pill.MSG/BUTTONS`, `yakon_rx.UI_TEXT` 그대로.
- **세션**: 알약은 `_prepared`, 처방전은 `drugs` 를 메모리에 10분 보관(처방전 OCR 줄은 보관하지 않음). 만료 → 410.
- **동시성**: uvicorn worker 1개 + `asyncio.Semaphore(1)`(알약·처방전 공용). 대기 60초 넘으면 503 `busy`. 계산은 `run_in_threadpool`.
- **입력 검증**: `/pill/*` key는 `pill/`, `/rx/*` key는 `prescription/` 로 시작. 확장자 jpg/png/webp, 10MB 이하. 사진은 디스크에 쓰지 않음.
- **배경 제거**(알약만): 알파 채널이 없으면 `bg.py` → `quality()`.
- **crop 저장**: `saveCrops=true`일 때만 배경 제거된 알약 조각. 처방전은 어떤 것도 저장하지 않음.
- **인증**: SG + 헤더 `X-Worker-Token`(`.env`). 불일치 401.
- **LLM 오류**: Bedrock 예외(AccessDenied·Throttling)는 502로 돌려주고 OCR 결과는 버림(저장 금지).

### 3-3. Docker
- 베이스 `python:3.13-slim` + `libgl1 libglib2.0-0` (opencv-contrib 비 headless 빌드가 필요로 함).
- **`constraints.txt`** 에 0-3 버전을 전부 고정하고 모든 `pip install` 에 `-c constraints.txt`:
  ```
  pip install -c constraints.txt paddlepaddle==3.2.2 paddleocr==3.7.0 paddlex[ocr-core]==3.7.2 opencv-contrib-python==4.10.0.84 …
  pip install -c constraints.txt torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu
  pip install -c constraints.txt --no-deps rembg==2.0.69
  pip install -c constraints.txt onnxruntime pymatting scikit-image pooch jsonschema tqdm
  ```
  이유: rembg ≥2.0.70 은 numpy≥2.3·pillow≥12.1 요구(충돌), ≤2.0.69 는 `opencv-python-headless` 를 끌고 옴(두 번째 cv2).
  `--no-deps` + constraints 로 numba(pymatting) 등이 numpy를 올리는 것도 막는다. 막히면 그 시점에 B안(onnxruntime 직접 호출) 검토.
- **빌드 마지막 검사** (실패 시 빌드 중단): `cv2.__version__ == "4.10.0"`, `pip list` 에 opencv 패키지 1개, numpy 2.1.3·pillow 11.3.0, rembg 배경 제거 1회 실행.
- OCR 모델: 이미지에 넣지 않고 `./deploy/ocr_models/...` 를 `~/.paddlex/official_models/` 에 연결(읽기 전용).
  `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`, `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`. 인터넷 차단 상태로 엔진 생성되는지 확인.
- rembg 모델 가중치: 빌드 단계에서 받아 이미지에 포함(`U2NET_HOME`) — 실행 중 다운로드 없음.
- `compose.yaml`: 포트 `0.0.0.0:8000:8000`, `./deploy:/app/deploy:ro`, `env_file: .env`, healthcheck `/health`, `restart: unless-stopped`. 비루트 사용자.

### 3-4. 배경 제거 모델 선택 실험 (EC2, 로컬 측정)
| 후보 | 근거 |
|---|---|
| `u2netp` | rembg README: "A lightweight version of u2net model." |
| `isnet-general-use` | "A new pre-trained model for general use cases." |
| `silueta` | "Same as u2net but the size is reduced to 43Mb." |
- 측정: (a) 시간 (b) quality() 통과율 (c) Colab 평가 결과와 후보 일치율 → 표로 보고 → 사용자 선택.
  (평가 사진은 이미 배경 제거 상태라 rembg는 Colab 평가에 쓰이지 않았음 — 별도 실험 필요)
- **가중치 라이선스도 함께 확인**해서 표에 적는다. `bria-rmbg` 금지("requires a paid agreement for commercial use").
- 판단 기준: 배경 제거 포함 요청 1건이 **33초 이상**이면 Plan B(브라우저 배경 제거) 검토 제안.

### 3-5. 서버 대조 (fixtures) — 알약·처방전 둘 다 통과해야 배포 완료
**OCR 지문** (UTF-8, sha256 hexdigest 전체):
- 처방전 (R-E3b): `lines = RxReader.read_lines(사진)` (rec_texts·rec_scores 순서, 좌표 제외)
  `sha256("\n".join(f"{l['text']}|{l['score']:.4f}" for l in lines).encode()).hexdigest()`
- 알약 (P-E1): `reads = PillIdentifier.prepare(사진)["reads"]` (회전 순서 config `[0, 90, 180, 270]`)
  `sha256("\n".join(f"{r['rot']}:{t}|{s:.4f}" for r in reads for t, s in zip(r["texts"], r["scores"])).encode()).hexdigest()`

**판정 순서** (EC2·Colab CPU 차이로 확신도 4번째 자리가 다를 수 있음 — 추론. 지문이 달라도 바로 실패로 끝내지 않음):
1. 글자 목록 동일 (필수) — 알약: fixture `photos[].texts` / 처방전: 줄 수 `n_lines`
2. 확신도 최대 차이 보고
3. 최종 결과 동일 — 알약: `analyze(photos[0], photos[1])` 의 band·imprint_match·top3 / 처방전: `decide(lines, fixture.llm_result) == fixture.drugs`
- 알약은 fixture `photos` 순서 그대로 `analyze(photos[0], photos[1])` (side "0"/"1"은 원본 라벨, 앞뒷면 의미 없음).
- 처방전은 LLM을 다시 호출한 결과로 비교하지 않는다.
- 지문이 다르면 opencv·paddle 버전부터 확인.

---

## 4. 백엔드 연결 (🔒 사용자 승인 후 PR)
- 새 모듈: `backend/app/modules/pill/{__init__,router,schemas,service}.py` — 기존 `modules/ocr` 패턴(CamelModel, `CurrentUser`, `/{user.id}/` 소유 확인).
  `POST /api/v1/pill/analyze|reject|imprint-choice|refine|confirm` → 워커로 전달.
- **`modules/ocr` 더미 교체** (작업자 본인이 10-12에 넣은 더미, 커밋 `e4ce109` 하나뿐 — 작업자 결정으로 교체 가능):
  `POST /api/v1/ocr/prescriptions` → 워커 `/rx/analyze`. 응답은 **(b) 기존 필드 유지 + 새 필드 추가**
  (`candidates[name, amount, timesPerDay, days]` 유지 + `drugs[…ui·candidates…]`, `privacy` 등 추가).
  기존 형식에 그대로 맞추면(a) 확신도 낮은 숫자도 확정값처럼 보여 안전 규칙이 무력화됨.
  ⚠ 프런트(`features/mypage/api.ts`)는 amount·timesPerDay·days 를 항상 number 로 가정 → "빈칸"(null) 표시 문제는 프런트 담당자에게 전달(프런트 수정 금지).
- 수정: `core/config.py` 에 `pill_worker_url`, `pill_worker_token` / `api/router.py` 에 `pill_router`.
- `httpx` 가 backend 의존성에 없으면 추가 여부를 사용자에게 먼저 묻는다(`uv.lock` 변경 → 팀 영향).
- 배포 값: 백엔드 EC2 `deploy/ec2/.env`(gitignore)에 `PILL_WORKER_URL`, `PILL_WORKER_TOKEN`.
- nginx `proxy_read_timeout 120s` → 처방전 최대 33초+여유면 변경 불필요(확인만). 백엔드 httpx timeout 90초.

---

## 5. 배포 순서
1. (PC) 문서 합치기 → 🔒 IAM plan/apply (prescription·Bedrock) → Dockerfile → 워커 앱 → `pytest`.
2. (PC) 🔒 `aws s3 sync deploy/ s3://<model_bucket>/models/ --exclude "*.zip" --exclude "*/.cache/*"` (구조 그대로 `models/{cnn,ocr_models,rx}/`).
3. (PC) 🔒 `git push` (브랜치 → PR → 머지는 팀 규칙대로).
4. (EC2, SSM) `git clone/pull` → `cd pill_model && bash scripts/fetch_models.sh && cp .env.example .env`(토큰) → `docker compose up -d --build`.
5. (EC2) `curl localhost:8000/health` → `python scripts/bench.py` (속도 5회 평균 + 3-5 대조, 알약·처방전).
6. (백엔드 EC2) 🔒 `.env`에 워커 주소 → `docker compose up -d backend` → 백엔드에서 워커 `/health`.

## 6. 완료 기준
- [x] 1차 plan/apply: 생성 13, 팀 자원 변경·삭제 0 (2026-10-22)
- [x] IAM 2차 apply (prescription·Bedrock) (2026-10-23) / [ ] Bedrock 첫 호출 AccessDenied 없음 (EC2)
- [x] (PC) 빌드 검사: cv2 4.10.0 · opencv 패키지 1개 · numpy 2.1.3 · pillow 11.3.0 · rembg 1회 실행
- [x] (PC) OCR 모델 "Using cached files", --network none 에서 엔진 생성
- [ ] `/health` 정상, image_index_size > 0
- [x] (PC) fixtures 대조 3-5 — 지문까지 전부 동일 / [ ] EC2 재확인: 알약 3쌍 + 처방전 3장 모두 글자 동일·최종 결과 동일 (다르면 원인 보고)
- [ ] 알약 1건 평균 ≤ 30초 (배경 제거 포함 따로), 처방전 1건 EC2 5회 평균 기록
- [ ] 백엔드 → 워커 호출 성공, 인터넷에서 8000 접근 불가 확인
- [ ] `git diff`에 계정 번호·버킷 이름·토큰·모델 파일·사진·노트북 없음
- [ ] devlog.md 기록

## 7. 아직 열린 항목
- 배경 제거 모델 (3-4 실험 후 사용자 선택, 라이선스 포함)
- crop 저장 동의 UI 문구 위치, 처방전 "빈칸"(null) 표시 (프런트 팀)
- 업로드 presign 운영 동작 (팀 작업 중 — 10-23 기준 미동작)
- CPU 크레딧(standard): 알약·처방전이 CPU를 나눠 씀 → EC2 측정 후 인스턴스 크기 재검토

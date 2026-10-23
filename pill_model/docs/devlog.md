# pill_model 개발 기록

## 2026-10-22 — Terraform 별도 스택 작성 (PLAN 2단계)

### 한 일
- `pill_model/infra/terraform` 작성: versions / variables / main / outputs / user_data.sh / *.example.
- `pill_model/.gitignore` 추가 (루트 .gitignore 는 수정하지 않음).
- 사전 조회(승인 불필요한 조회만): 도구 버전, 자격 증명, 버킷 목록, IAM 정책, VPC·서브넷·SG.
- `terraform init` → `validate` → `plan -out=tfplan` 실행.

### 실행 결과
- 도구: aws-cli 2.36.7, session-manager-plugin 1.2.835.0, Terraform 1.15.8, AWS provider 6.70.0.
- 권한: 그룹 정책 `DE-AI-Resource-Isolation-Policy` 에 `ec2:* / s3:* / iam:* / ssm:*` 포함, us-east-1 허용 → 생성 권한 문제 없음(조회로 확인, apply 전이라 실제 생성은 미검증).
- plan: **`Plan: 13 to add, 0 to change, 0 to destroy.`** 팀 자원(VPC·서브넷·백엔드 SG·데이터 버킷)은 `data` 읽기만.
- 팀 state `pill-check/dev/terraform.tfstate` 수정 시각 변화 없음(plan 전후 동일).

### 발견한 것 / 막힌 것
1. **계획서와 실제 계정이 다름**: PLAN 2-1은 "실제 자원 이름이 `agent-de-ai-01-*`"라고 했지만, 조회 결과
   실행 중인 백엔드 인스턴스는 `pill-check-dev-ec2` (VPC `pill-check-dev-vpc`, 퍼블릭 서브넷 `pill-check-dev-public-us-east-1a`, SG `pill-check-dev-ec2`).
   `agent-de-ai-01-vpc` 에는 인스턴스가 없음. → tfvars 에는 `pill-check-dev-*` 값을 넣고 plan 함. **apply 전에 사용자 확인 필요.**
2. 루트 .gitignore 의 `docs` 규칙 때문에 이 파일이 커밋에서 빠지는 문제 → `pill_model/.gitignore` 에 `!docs/` 로 다시 포함.
3. 데이터 버킷에 `silver/pill_identification/` 이 아직 없음 (silver 에는 drug_product, dur_contraindication, health_food_product 만).
   → 앱 시작 시 image_url 사전이 비게 됨(설계상 `image_url=null` 로 계속 동작). 파이프라인 팀 확인 필요.

### 남은 일
- ~~🔒 `terraform apply tfplan` (사용자)~~ → 완료 (아래)
- `upload_bucket_name` (팀 확인 대기)

## 2026-10-22 — apply 결과 확인

### 실행 결과
- 사용자 실행: `Apply complete! Resources: 13 added, 0 changed, 0 destroyed.` (교육 계정 de-ai-21 생성 권한 문제 없음)
- 조회로 확인 (describe/get만):
  - EC2: running, t3.medium, credit `standard`, IMDSv2 `required`/hop limit 2, 키 페어 없음, 상태 검사 ok/ok
  - 볼륨: gp3 30GB, 암호화
  - SSM: `Online` (Amazon Linux 2023, agent 3.3.5390.0) → 접속 가능 상태
  - 워커 SG: 인바운드 TCP 8000 ← 백엔드 SG 하나만, 아웃바운드 전체
  - 모델 버킷: 퍼블릭 차단 4개 true, AES256, BucketOwnerEnforced, DenyInsecureTransport, 객체 0개
  - IAM: AmazonSSMManagedInstanceCore + ModelList/ModelRead/CropWrite/SilverList/SilverRead (업로드 버킷 권한은 이름 미정이라 없음)
  - state: `pill-model.tfstate` 새로 생김, 팀 `terraform.tfstate` 수정 시각 그대로
- user_data (EC2 부팅 콘솔 로그): `Docker version 25.0.14`, `Docker Compose version v2.29.7`, cloud-init 오류 없이 종료(약 125초).

### 메모
- 사용자 PC(Docker Desktop)의 Compose 는 v5.5.1 이라 EC2(v2.29.7)와 버전이 다르다. compose.yaml 은 두 버전 모두에서 되는 기본 문법만 쓴다.
- 아직 확인 못 한 것: 컨테이너 안에서 IAM 역할 자격 증명(IMDSv2 hop 2)으로 S3 접근 — 3단계 워커 실행 때 확인.

## 2026-10-23 — 낱알 이미지 경로 정정, 업로드 버킷 권한

### 배경 (인프라 담당 답변)
- `silver/pill_identification/` 경로는 없다. 낱알식별 데이터는 `silver/drug_product/snapshot=…/data.parquet` 의 `pills` 목록 안에 있음.
- 운영 업로드 버킷은 `pill-check-uploads-<계정>` (팀 Terraform 소유), purpose=pill 사진은 `pill/` 아래.

### 확인 (조회만, S3 쓰기 없음)
- `silver/_latest.json`: snapshot 2026-10-23, `tables.drug_product = 2026-10-23`.
- `drug_product` parquet 370MB, 20 row group, 39,814행. `pills` = `list<struct{image_id, item_image, print_front, print_back, drug_shape, color_class1, …}>`
  (파이프라인 `pipeline/silver/tables.py` PILL_IDENTIFICATION 정의와 일치).
- pyarrow S3 범위 읽기로 `item_seq`, `pills` 두 컬럼만: 약 14.5초, 메모리 7.7MB.
  pills 있는 품목 21,690 / 낱알 행 21,707 / 2장 이상 품목 10 / item_image 빈 값 0 / 호스트 전부 `nedrug.mfds.go.kr`.
  원본 25,463행 − silver에서 빠진 3,756행(`pill_rows_dropped`, 허가 취소 등) = 21,707 → 숫자 일치.
- 업로드 버킷: 담당자 답변과 달리 **이미 존재**(2026-10-22 23:43 생성, 태그 ManagedBy=terraform, `pill/` 경로 있음).

### 변경
- IAM: 데이터 버킷 읽기 경로 `silver/pill_identification/*` → `silver/drug_product/*` (List prefix 동일하게).
- 업로드 버킷: 팀 Terraform이 이미 생성(2026-10-22 23:43, 담당자 답변 이후) → 사용자 결정으로 `data "aws_s3_bucket" "upload"` 조회 방식 유지. tfvars에 이름 설정 → `pill/*` GetObject 추가. bronze 권한은 넣지 않음(silver로 충분, 사용자 확인).
- plan: **`Plan: 0 to add, 1 to change, 0 to destroy.`** (aws_iam_role_policy.worker in-place)
- plan.md 2-1/2-2/3-1/7, claude.md 2절 사실관계 정정.

### 남은 일
- 🔒 `terraform apply tfplan` (사용자) — IAM 정책 1개 변경
- 3단계 준비물: `pill_model/deploy/`에 Drive 파일, Colab 패키지 버전 목록

## 2026-10-23 — 폴더 재정리 (처방전 OCR 추가 방향, Plan A)

### 결정 (사용자)
- 처방전·약봉투 OCR 을 같은 워커에 추가 (Plan A): PaddleOCR 인스턴스 1개를 알약·처방전이 공유, `/rx/*` API 추가.

### 한 일 (로컬, deploy/ 는 gitignore)
- `deploy/` → `cnn/`(cnn_v5.pt, gallery_v5.npy, gallery_index.csv, pill_db.csv, config.json), `ocr_models/paddleocr_v5_korean_2026-10-14/`(det·rec·MODEL_CARD), `rx/`(비어 있음).
- OCR zip 압축 해제 시 HuggingFace 캐시(`.cache/`, `.gitattributes`) 제외. 원본 zip 은 deploy/ 에 남겨 둠(S3 업로드 시 제외).
- `yakon_pill.py` → `app/pill/yakon_pill.py` 이동, sha256 동일 확인(수정 없음).

### 확인한 사실
- `yakon_pill._make_ocr()` 은 모델 경로 없이 `PaddleOCR(lang="korean", det 640 max, rec batch 16, …)` → 실행 시 기본 모델을 내려받음.
  MODEL_CARD 의 det/rec(PP-OCRv5_server_det + korean_PP-OCRv5_mobile_rec)와 같은 이름 → 같은 모델로 추정(파일 대조는 아직).
- `PillIdentifier(deploy_dir, load_ocr=False)` 후 바깥에서 `pid.ocr = 공유 인스턴스` 를 넣으면 yakon_pill 수정 없이 공유 가능 (`read_text` 가 `self.ocr.predict` 만 사용).
- MODEL_CARD: paddleocr 3.7.0, paddlepaddle 3.3.0.
- 백엔드 업로드 key = `{purpose}/YYYY/MM/DD/{owner}/{uuid}.{ext}`, purpose ∈ {prescription, pill}. 처방전 사진은 `prescription/` → 워커 IAM 에 읽기 권한 추가 필요.

## 2026-10-23 — 처방전 준비물 수령·검토, opencv 단일 버전 검토

### 받은 것
- `app/rx/yakon_rx.py` (R-E2 검증본, 수정 금지), `deploy/rx/` (config_rx.json, permit_names.csv 42,897행, dose_envelope.json)
- `tests/fixtures/pill/*.expected.json` 3개 (cv2 4.10.0 환경), `tests/fixtures/rx/*.expected.json` 3개 (OCR 원문 없음 — 지문·LLM 결과·판정만 → 커밋 가능)
- `app/pill/yakon_pill.py` 는 커밋본과 동일(git diff 없음)

### 확인한 사실
- `RxReader(deploy_dir, ocr=…, llm_client=…)` → 공유 OCR 엔진·boto3 클라이언트를 밖에서 넣을 수 있음 (yakon_rx 수정 불필요).
- ⚠ `config_rx.json` 의 `"per_call_limit": false`. `analyze()` 는 `read_lines(img)` 를 인자 없이 호출 → 설정값을 따름.
  공유 엔진(640)에 false 면 처방전이 640 으로 검출됨 → R-E3 ② 결론(true)과 다름. 사용자 확인 필요.
- 패키지 메타데이터 (pip download --no-deps, 설치 안 함):
  - paddlex 3.7.2 → `opencv-contrib-python==4.10.0.84` 고정 (ocr-core extra)
  - rembg 2.0.70~2.0.86 → `numpy>=2.3`, `pillow>=12.1` (검증 환경 numpy 2.1.3·pillow 11.3.0 과 충돌), opencv 의존 없음
  - rembg ≤2.0.69 → `opencv-python-headless`(버전 무제한) 요구 → 두 번째 cv2 패키지가 설치됨
  - rembg 2.0.69 코드: `bg.py` 가 `from cv2 import …`, `sessions/sam.py` 가 `import cv2` → contrib 의 cv2 로도 동작할 것으로 추정
  → 후보: opencv-contrib-python 4.10.0.84 하나 + `rembg==2.0.69 --no-deps` + 나머지 의존성 개별 설치. 빌드에서 `cv2.__version__` 검사.

## 2026-10-23 — 결정 반영: per_call_limit, 문서 합치기, IAM 2차 plan

### config_rx.json 변경 (사용자 승인)
- `"per_call_limit": false` → `true` (한 줄만, JSON 검증 통과). 코드 수정 없음.
- sha256 원본 `3ea98dd70d47a60e83ecc307c3eca2cbf2f215ad197f34478c576dd77c78c21b` (Drive 원본 접두어 `3ea98dd70d47a60e…` 와 일치)
  → 변경 후 `73251b1fa6b8ea5923fd8cfe1de55709dc6196ed6a5cf642181ec7adb625fb56`
- 근거: Colab R-E3 ② 는 `read_lines(p, per_call_limit=True)` 인자로 640 엔진 = 1280 엔진(글자·확신도 동일) 확인. config 를 true 로 하면 `analyze()` 가 같은 경로.
- permit_names.csv: 42,714행 = 고유 ITEM_SEQ 42,714 (wc -l 42,898 은 이름 안 줄바꿈 때문). dose_envelope.json 33,921품목. 전달 내용과 일치.

### .gitignore 구멍 수정
- `tests/fixtures/*.png|jpg` 는 하위 폴더(`pill/`, `rx/`)에 적용되지 않음 → 처방전 사진이 커밋될 수 있었음.
  `tests/fixtures/**/*.{png,jpg,jpeg,webp,heic}` (대·소문자)로 변경.

### 사진 위치
- fixture 사진 9장이 `tests/fixtures/` 에 없음(최근 3시간 내 추가된 이미지 0). 저장소 `data/ocr_evaluation/`(루트 gitignore)에 `rx_0001.jpg`, `bag_0001.jpg` 만 있음. 알약 6장·`약봉투7.jpg` 없음 → 사용자 확인 대기.

### 문서 합치기
- `CLAUDE(model).md`·`PLAN(model).md`(10/23 처방전 반영본) + PC 정정(계정 자원 이름, silver drug_product, 업로드 버킷) → `claude.md`·`plan.md`.
- 추가 반영: opencv-contrib 4.10.0.84 단일, rembg 2.0.69 --no-deps + constraints, OCR 지문 공식·단계 판정(plan 3-5), 백엔드 `modules/ocr` 더미 교체 허용(응답 (b)안), S3 `models/{cnn,ocr_models,rx}/`.

### IAM 2차 plan
- 이전 plan(drug_product·pill/*)은 apply 되지 않은 상태였음(현재 정책 조회로 확인) → 이번 plan 에 함께 포함.
- Bedrock 기반 모델 ARN 은 `data "aws_bedrock_inference_profile"` 로 조회(리전 하드코딩 없음).
- `Plan: 0 to add, 1 to change, 0 to destroy.` — aws_iam_role_policy.worker 만 변경:
  silver 경로 → drug_product / UploadRead(pill/*, prescription/*) 추가 / RxLlmInvoke(프로필 ARN + 기반 모델 3개) 추가.

### fixture 사진 확인 (같은 날, 사용자가 추가)
- 알약: `tests/fixtures/pill/{29002,34342,39916}/` — 품목별 하위 폴더, 각 40장(RGBA PNG, 배경 제거됨) + Thumbs.db.
  fixture 가 요구하는 6장 모두 있음 → 테스트 경로는 `tests/fixtures/pill/<code>/<photos[].file>`.
  나머지 34장씩은 기대값 없음 → 속도 측정(bench) 표본으로만 사용 가능.
- 처방전: `tests/fixtures/rx/` rx_0001.jpg(4000x3000, 4.7MB), bag_0001.jpg(4000x3000, 4.4MB), 약봉투7.jpg(720x534) — 3장 모두 있음.
  ⚠ 저장소 `data/ocr_evaluation/…/rx_0001.jpg`(137KB)와 **다른 파일** → 대조에는 tests/fixtures 쪽만 사용.
- git: 사진·Thumbs.db 모두 제외 확인, 커밋 대상은 *.expected.json 6개뿐.

## 2026-10-23 — IAM 2차 apply 확인, Docker 이미지 빌드, fixture 대조 통과 (PC)

### IAM (사용자 apply 후 조회)
- 정책 6문장: ModelList·ModelRead·CropWrite·SilverList/Read(`silver/drug_product/*`, `_latest.json`)·UploadRead(`pill/*`, `prescription/*`)·RxLlmInvoke(프로필 + 기반 모델 3리전) — plan 과 일치.

### 정리한 파일
- `CLAUDE(model).md`, `PLAN(model).md` (claude.md·plan.md 로 합침), OCR zip(풀린 파일과 pdiparams·json sha256 대조 후), 적용 끝난 `tfplan` 삭제.

### Docker (PC Docker Desktop 29.8, linux/x86_64)
- 새 파일: Dockerfile, constraints.txt, requirements.txt, .dockerignore, compose.yaml, .env.example, scripts/check_env.py, app/ocr_engine.py, scripts/verify_fixtures.py
- 확인한 사실: paddlepaddle 3.2.2 cp313 manylinux 휠 PyPI 존재, torch 2.11.0+cpu cp313 존재. 백엔드 uv.lock: fastapi 0.143.0·uvicorn 0.54.0·pydantic 2.14.1·httpx 0.28.1(이미 있음 → uv.lock 변경 불필요).
- rembg 2.0.69 의 `__init__` 은 bg·session_factory 만 import → gradio·aiohttp(cli 전용) 불필요.
- 빌드 성공, 이미지 1.36GB. pip 경고 `rembg 2.0.69 requires opencv-python-headless, which is not installed` 는 의도한 것(A안).
- check_env.py 결과: numpy 2.1.3 · pillow 11.3.0 · pandas 2.2.3 · scipy 1.16.3 · paddlepaddle 3.2.2 · paddleocr 3.7.0 · paddlex 3.7.2 ·
  opencv-contrib-python 4.10.0.84(opencv 패키지 1개) · cv2 4.10.0 · rapidfuzz 3.14.6 · timm 1.0.30 · rembg 2.0.69 · torch 2.11.0+cpu · rembg 1회 실행 OK.
  constraints 덕분에 numba 0.68.0·scikit-image 0.26.0·onnxruntime 1.31.0 이 numpy 를 올리지 않고 설치됨.
- `requirements.lock.txt` (pip freeze 108줄) 저장.
- rembg 가중치(빌드 때 포함): u2netp 4.6MB · silueta 44MB · isnet-general-use 179MB.
  라이선스: 배포처 danielgatis/rembg = MIT, 원 모델 U-2-Net(u2netp·silueta 기반) = Apache-2.0, DIS(isnet) = Apache-2.0 (gh api 조회).
  가중치 파일 자체에 별도 라이선스 표기는 없음 → 저장소 라이선스가 적용된다고 보는 것은 추론.

### fixture 대조 (컨테이너, `--network none`, deploy·ocr_models 읽기 전용 연결, LLM 호출 없음)
- 로그: `Model files already exist. Using cached files.` (det·rec 둘 다) → 인터넷 없이 엔진 생성. load 18.2초, 공유 엔진 `pill.ocr is rx.ocr` = true.
- 알약 3쌍(29002·34342·39916): 사진 6장 **지문 6/6 동일**, 글자 동일, quality 동일, band A·imprint_match 1.0·Top-3·next_step(top1) 동일, 점수 최대 차이 0.0.
- 처방전 3장(bag_0001·rx_0001·약봉투7): **지문 3/3 동일**, 줄 수 27·20·116 동일, `decide(lines, llm_result)` = fixture drugs (다른 약 0).
- 결과 `{"pill_pass": true, "rx_pass": true, "fingerprints_all_same": true}`
- 참고 시간(PC 8 CPU, 측정 1회라 평균 아님): 알약 사진 1장 prepare 6.9~9.9초, 처방전 OCR 8.5~10.4초. EC2(t3.medium 2 vCPU)는 더 느릴 것(추론) → EC2 5회 평균 필요.

## 2026-10-23 — S3 모델 업로드, presign 확인, 워커 권한 시뮬레이션

### S3 업로드 (사용자 요청으로 실행)
- `aws s3 sync deploy/ s3://<model_bucket>/models/ --exclude "*/.cache/*" --exclude "*Thumbs.db"` → 19개 객체, 191,174,651 바이트.
  dryrun 으로 목록 먼저 확인. cnn_v5.pt·gallery_v5.npy·config_rx.json·server_det pdiparams 크기 로컬과 동일.

### 업로드(presign) 동작 확인
- 운영 백엔드 `POST /api/v1/uploads/presign` (guest, purpose=pill) → HTTP 200, 업로드 버킷 `pill/2026/10/23/guest/<uuid>.png` URL 발급(300초, 10MB). PUT 은 하지 않음.
- 백엔드 역할 `pill-check-dev-ec2-app`: 업로드 버킷 Put/Get 있음. 버킷 CORS: 백엔드 EC2 공인 IP 오리진에서 GET·PUT 허용.
- 버킷에는 `pill/2026/10/22/guest/…png` 26바이트 1개(테스트 흔적)만 있음, `prescription/` 없음.
- 원인: 프런트 `features/mypage/api.ts` 에 presign·ocr 함수는 있으나 `MedicineRegistration.tsx` 는 호출하지 않고 `setTimeout` 데모 흐름 → **백엔드 presign 은 동작, 프런트 미연결**.
- 백엔드 `core/config.py` 는 `extra="ignore"` → `.env` 에 PILL_* 를 먼저 넣어도 기동에는 영향 없음(코드에서 아직 안 읽음).

### 백엔드 EC2 SSM 원격 명령 — 실행 못 함
- `.env` 키 이름만 보는 읽기 전용 `aws ssm send-command` 가 Claude Code 자동 모드 보안 판정으로 거부됨 → 우회하지 않고 사용자에게 수동 절차 안내.

### 워커 역할 권한 (iam simulate-principal-policy, 조회)
- allowed: Bedrock InvokeModel(프로필·us-east-2/us-west-2 기반 모델), 모델 버킷 models/* Get, crops/* Put, silver drug_product Get, 업로드 prescription/*·pill/* Get
- implicitDeny(의도대로): 다른 모델(sonnet), models/* Put, 다른 silver 테이블, 업로드 버킷 Put
- 정책 평가 기준 확인이며 실제 호출은 EC2 컨테이너에서 확인 필요.
- 워커 EC2: running ok/ok, SSM Online, CPUCreditBalance 480 (t3.medium 최대 576).

## 2026-10-23 — 워커 API · 백엔드 연결 · 프런트 연동 (PC)

### 워커 API (`app/main.py` 외 6개, yakon_* 수정 없음)
- `settings.py`(환경변수) · `schemas.py`(camelCase, yakon 출력 dict 는 키만 변환) · `sessions.py`(메모리 TTL 10분, 처방전은 drugs 만 보관) ·
  `storage.py`(key 형식 검사·10MB·crop 저장, 경로에 사용자 ID 없음) · `images.py`(silver item_seq·pills 두 컬럼 범위 읽기, 실패해도 기동) · `bg.py`(알파 없을 때만 rembg, 긴 변 2048 축소, bria 금지)
- 엔드포인트: `/health`, `/pill/analyze|reject|imprint-choice|refine|confirm`, `/rx/analyze|confirm`. 인증 `X-Worker-Token`(hmac 비교), 동시성 1(Semaphore, 60초 대기 후 503 busy).
- 오류 코드: 400 bad_key/bad_image, 404 not_found, 410 expired, 413 too_large, 502 llm_unavailable(Bedrock 예외, OCR 결과 버림), 503 not_ready/busy.
- 재촬영: `prevSessionId` 로 시도 횟수를 이어받아 on_reject 흐름(각인 입력 → 재촬영 → 종료) 유지.

### 테스트 (컨테이너, pytest 8.4.2 는 실행 때만 설치) — 30 passed (119초)
- 단위·API(가짜 모델) 24개: 인증 401, key 규칙, 대화 흐름 전체, crop 동의 시에만 저장, 세션 만료 410, rx 502 등.
- **통합(실제 모델 + fixture, LLM 은 fixture llm_result 재생) 6개**: 알약 3쌍 step·band·imprintMatch·Top-3 = Colab, 처방전 3장 API 응답 drugs = fixture drugs.

### 백엔드 (승인: "교체 배포 하면 좋을 것 같은데")
- 새 `modules/pill` (워커 전달, 업로드 owner(회원 ID/guest) 확인) · `modules/ocr` 에 `OCR_PROVIDER=worker` 추가(기존 mock/claude/textract 유지),
  응답은 (b) 기존 candidates 유지(숫자는 ui=미리 채움만, 나머지 null) + drugs·sessionId·privacy 등 추가, `/ocr/prescriptions/confirm` 추가.
- `/ocr/prescriptions` 를 비회원(guest 경로)도 쓸 수 있게 CurrentUser → OptionalUser (채팅 사진 첨부가 비회원도 가능하므로).
- config: `pill_worker_url`, `pill_worker_token`, `pill_worker_timeout_seconds=90`. httpx 는 이미 의존성에 있음(uv.lock 변경 없음).
- 백엔드 pytest 16 passed (새 7개). ruff: 새·수정 파일 오류 0 (기존 44건은 그대로).
- PC 실연결: 워커 컨테이너(8001, LOCAL_UPLOAD_DIR) ↔ 로컬 백엔드(8000) — 알약 analyze→reject(top1)→reject(top3)→imprint-choice→refine→confirm 전부 200,
  1위 201505259·Top-3 fixture 동일. 남의 owner key 403, 토큰 없이 워커 직접 401, LLM 미설정 rx 503.
  (이때 analyze 69초는 백그라운드 벤치와 CPU 를 같이 써서 측정값 아님)

### 프런트 (사용자가 프런트 담당 겸임 — 직접 요청)
- `features/photo/api.ts`: 업로드(presign → S3 PUT, jpg/png/webp 아니거나 10MB 초과면 브라우저에서 JPEG 변환), 알약·처방전 API, 오류 문장.
- 채팅 사진 첨부: 사진 종류 선택(알약 앞·뒤 2장 / 처방전 1장) + crop 저장 동의 체크박스(동의 문구 + 면책 문장) → `PillDialog`(top1·top3·각인·색·재촬영·종료, 문장·버튼은 워커 응답 그대로) / `RxCandidates`.
  약 확정 → 기존 챗봇 질문으로 연결. 데모 `DrugCandidates.tsx` 삭제.
- 사진 종류 판단: 사용자가 고르는 방식(Plan A) + 잘못 고른 경우 안내(처방전에서 약 0개 → 알약으로 다시, 알약 quality 문제 → 종류 바꿔 다시).
- 마이페이지 약 등록: 실제 인식 → 약 여러 개면 선택, 이름 미확정이면 후보 선택(→ `/ocr/prescriptions/confirm` 으로 용법 상한 검증), ui 가 "미리 채움"이 아닌 칸 강조, 빈칸은 비워 둠.
  저장하면 **내 복용약에 누적**(건강정보와 함께 브라우저 저장), 각 약 아래 "1일 n회 · 1회 n정 · n일분 · 시작일" 표시.
- typecheck·lint 통과.

### 막힌 것
- 워커 EC2 SSM 명령·AWS 조회가 Claude Code 자동 모드 보안 판정으로 거부(설정 규칙 추가 전) → EC2 점검은 아직 못 함.

### PC 벤치 (컨테이너 `--network none`, 8 CPU — EC2 t3.medium 은 더 느릴 것, 추론)
- 알약 1건(사진 2장, 배경 이미 제거된 fixture): 29002 평균 16.4초 · 34342 15.2초 · 39916 17.2초 (첫 요청 제외 3회), Top-3 전부 Colab 동일.
- 배경 제거 3개 비교 — fixture 알약을 단색/체크무늬 배경에 **합성**해 JPEG 로 만든 뒤 rembg 로 다시 지움 (코드당 2쌍, 총 6쌍):

| 모델 | 배경 | 배경 제거 평균(최대) 초 | quality 통과 | Colab 1위 일치 | 정답 Top-3 안 |
|---|---|---|---|---|---|
| u2netp | 단색 | 1.74 (2.68) | 2/6 | 4/6 | 6/6 |
| u2netp | 무늬 | 1.49 (1.93) | 2/6 | 4/6 | 6/6 |
| isnet-general-use | 단색 | 8.68 (20.42) | 2/6 | 3/6 | 4/6 |
| isnet-general-use | 무늬 | 5.31 (7.27) | 2/6 | 4/6 | 6/6 |
| silueta | 단색 | 2.10 (2.70) | 2/6 | 4/6 | 6/6 |
| silueta | 무늬 | 2.38 (3.08) | 2/6 | 4/6 | 6/6 |

- 해석(확신 낮음): 합성 사진이라 실제 촬영과 다름. quality 2/6 은 세 모델 공통이라 모델보다 합성 방식(알약 가장자리 등) 영향일 가능성. isnet 은 느리고 단색에서 정확도도 낮음.
  → 기본값 u2netp 유지(가장 빠름, 정확도 동률). 최종 선택은 실제 촬영 사진으로 EC2 에서 재측정 후.

## 2026-10-23 — 워커 EC2 첫 배포 (사용자가 SSM 웹 콘솔로 실행)
- `docker compose up -d --build` → healthy. `/health`: pill·rx·llm 모두 true, loadSec 19.2, cv2 4.10.0.
- ❌ `imageIndex.status = error, error = ArrowTypeError` (0.6초 — 파일을 읽기 전에 실패)
  - 원인: `pq.read_table` 은 dataset 방식이라 경로의 `snapshot=2026-10-23` 을 파티션 컬럼(dictionary)으로 만들고,
    파일 안에도 `snapshot`(string) 컬럼이 있어 스키마 병합 실패. PC 로컬에서 같은 경로·컬럼으로 재현:
    `Unable to merge: Field snapshot has incompatible types: string vs dictionary<values=string, ...>`
  - 해결: PC 실측 때 쓴 `pq.ParquetFile(path).read(columns=["item_seq","pills"])` 로 변경 (`images.read_urls`), 재현 테스트 추가 (unit+api 25 passed).

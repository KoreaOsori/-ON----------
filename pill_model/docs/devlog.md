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

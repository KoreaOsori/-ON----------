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
- 🔒 `terraform apply tfplan` (사용자)
- `upload_bucket_name` (팀 확인 대기)

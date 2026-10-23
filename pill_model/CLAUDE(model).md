# pill_model — 약ON 낱알 식별 워커 (Claude Code 작업 규칙)

이 폴더는 약ON 저장소의 **독립 서비스**다. 알약 사진 2장(앞·뒤) → 각인 OCR + CNN 외형 + RRF 결합 → 후보와 대화 단계 응답.
메인 백엔드(`backend/`)와는 **REST(HTTP)로만** 연결하고, 별도 EC2에서 Docker로 실행한다.
작업 순서와 세부 설계는 `PLAN.md`를 따른다. 이 파일은 "지켜야 할 규칙"만 담는다.

## 0. 작업자 정보
- 작업자: 서동현 (Python 약 4개월). **코드에는 한국어 주석을 달고, 바꾼 이유를 짧게 설명**한다.
- 환경: Windows PC + VS Code. 서버 접속은 **SSM Session Manager** (SSH·22번 포트 없음, 팀 방식).
- 운영 흐름(팀 방식): PC에서 수정 → `git push` → EC2에서 `git pull` → `docker compose up -d --build`.

## 1. 절대 규칙 (예외 없음)
1. **승인 없는 실행 금지** — 아래는 실행 전에 반드시 명령을 보여주고 사용자 승인을 받는다.
   - `terraform apply`, `terraform destroy`, `terraform import`, `terraform state ...`
   - `aws s3 cp/sync/rm`, `aws ec2 ...`(조회 제외), `aws iam ...`(조회 제외), `aws ssm send-command`
   - `git push`, `git commit`(커밋 메시지 확인), PR 생성
   - 비용이 드는 것, 외부에 반영되는 것, 삭제하는 것 전부
   - 조회(`plan`, `describe`, `get`, `list`, `ls`)와 로컬 테스트는 승인 없이 해도 된다.
2. **팀 자원은 읽기만** — `infra/`, `deploy/`, `pipeline/`, `vector_pipeline/`, `frontend/` 는 수정하지 않는다.
   `backend/` 는 `PLAN.md` 4단계의 **새 파일 추가 + `api/router.py`·`core/config.py` 몇 줄**만, 사용자 승인 후 PR로.
   팀 Terraform 상태(`pill-check/dev/terraform.tfstate`)는 절대 건드리지 않는다. 이 스택의 키는 `pill-check/dev/pill-model.tfstate`.
3. **비밀값·식별값을 코드에 쓰지 않는다** — AWS 계정 번호, 버킷 이름(계정 번호 포함), RDS 주소, IP, 토큰.
   → Terraform은 `data` 조회·`aws_caller_identity`·`terraform.tfvars`(gitignore), 앱은 환경변수/`.env`(gitignore).
   커밋 전에 `git diff --cached` 에서 12자리 숫자·`amazonaws.com`·`token` 문자열을 검사해 보고한다.
4. **모델·데이터 파일은 git에 올리지 않는다** — `*.pt`, `*.npy`, `deploy/`, `crops/`, `*.parquet`, 사진. 원본은 S3 모델 버킷.
5. **식별 로직을 바꾸지 않는다** — `app/pill/yakon_pill.py`, `app/rx/yakon_rx.py` 는 Colab에서 검증한 그대로 복사해 쓴다(점수 계산·정규화·밴드·문구).
   수정이 필요해 보이면 고치지 말고 이유와 함께 사용자에게 먼저 묻는다. 래퍼(API·S3·세션)만 새로 작성한다.
6. **애매하면 진행하지 말고 질문한다.** 선택지가 있으면 Plan A/B 형식(구성 / 예측 결과 / 근거 유형[텍스트 추론 or 실제 조회·실행] / 되돌릴 수 있는지)으로 제시한다.

## 2. 고정된 결정 (2026-10-22, 사용자 확정)
| 항목 | 결정 |
|---|---|
| 위치 | 저장소 최상위 `pill_model/` (front·backend와 같은 층) |
| 인프라 | `pill_model/infra/terraform` **별도 스택**. 팀 VPC·서브넷·백엔드 SG·데이터 버킷은 `data`로 읽기만 |
| state | 팀 state 버킷, **다른 키** `pill-check/dev/pill-model.tfstate` (`use_lockfile = true`). 버킷 이름은 `backend.hcl`(gitignore). 팀 state 버킷이 없으면 멈추고 질문 |
| EC2 | t3.medium, **credit standard**, Amazon Linux 2023, gp3 30GB 암호화, IMDSv2, 퍼블릭 서브넷(NAT 없음) |
| 접근 | 워커 SG 인바운드 = 백엔드 SG에서 TCP 8000만. 인터넷 인바운드 없음. 접속은 SSM |
| 사진 전달 | 백엔드는 S3 `object_key`(purpose=`pill`)만 넘긴다. 워커가 업로드 버킷에서 읽는다 |
| 낱알 공식 사진 | silver `pill_identification`의 `item_image`(URL)를 시작 시 읽어 후보에 `image_url`로 붙인다 |
| 저장 정책 | 처방전·약봉투 사진은 저장 안 함. 알약은 **배경 제거된 조각만**, 사용자 동의 시 모델 버킷 `crops/`에 저장. 경로에 사용자 ID 넣지 않음 |
| 배경 제거 | 워커에서 rembg (모델은 `PLAN.md` 실험으로 결정, **기본값 bria-rmbg 사용 금지** — 상업 이용 유료). 요청 1건 **33초 이상**이면 브라우저 방식 검토를 사용자에게 제안 |
| 팀 자원 참조 | 실제 계정 이름(`agent-de-ai-01-*`)이 저장소 팀 Terraform(`pill-check-dev-*`)과 다름 → **ID를 tfvars 변수로** 받음(이름 조회 금지). 워커 SG는 새로 만들고 기존 ec2-sg를 붙이지 않음 |
| 생성 방식 | 콘솔 생성 안 함. 이 스택의 `terraform plan` → 사용자 `apply` |
| 실행 권한 | `terraform apply`는 사용자(교육 계정 `de-ai-21`)가 직접 실행 |
| OCR 설정 | 알약: `deploy/cnn/config.json` 그대로 (검출 640, 4방향, rec batch 16) / 처방전: `deploy/rx/config_rx.json` (검출 1280, 긴 변 2500, 초해상도 없음) — 바꾸지 않음 |
| 처방전 OCR | 같은 워커에 `/rx/*` 추가 (2026-10-23). `app/rx/yakon_rx.py` 수정 금지(R-E2 검증본). 사진·글자·LLM 입출력 저장·로그 금지 |
| 버전 | Python 3.13 · paddlepaddle 3.2.2(CPU, 3.3.x 금지) · paddleocr 3.7.0 · paddlex 3.7.2 |

## 3. 검증 원칙 (결과 보고할 때 지킬 것)
- "됐다"고 말하기 전에 **실제 실행 결과**(명령 출력·응답 JSON·시간)를 붙인다. 추론이면 추론이라고 쓴다.
- 같은 사진으로 **워커 결과 = Colab(`yakon_pill`) 결과**인지 대조한다(후보 순서·밴드·imprint_match). 다르면 그 자체를 보고.
- 속도는 첫 요청(모델 준비) 제외 5회 이상 평균. 목표: 요청 1건 30초 이하(Colab CPU 실측 약 23초).
- 단계마다 "확신이 낮은 부분"을 숨기지 말고 마지막 보고에 남긴다.

## 4. 개발 기록
작업이 끝날 때마다 무엇을 했고 무엇이 막혔는지(에러 원문·원인·해결)를 `pill_model/docs/devlog.md`에 날짜와 함께 추가한다.
최종 통합 문서와 발표 자료에 그대로 쓰인다.

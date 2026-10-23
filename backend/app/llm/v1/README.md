# 약·건강기능식품 LLM v1

이 디렉터리만으로 실행하는 FastAPI / Bedrock RAG 모듈이다. 모델 학습이 아니라 기존 제품 DB와 Claude를 연결한다. 기존 백엔드 파일은 변경하지 않는다.

## 실행 및 Swagger

기존 backend/pyproject.toml의 의존성(fastapi, uvicorn, sqlalchemy, asyncpg, boto3, pydantic-settings)이 설치된 Python 3.12 환경을 사용한다. 프로젝트 루트에서:

```powershell
python -m uvicorn app.llm.v1.api:app --app-dir backend --host 127.0.0.1 --port 8011
```

EC2 역할과 네트워크가 준비되면 **.env 없이** 기본 설정으로 실행한다. DB는 아래 고정 설정과 Secrets Manager를 사용한다. Bedrock 모델 등의 선택 설정만 필요하면 `backend/app/llm/v1/.env.example`을 참고한다. 기존 backend/.env는 읽지 않는다.

- Swagger: http://127.0.0.1:8011/docs
- 모델 설정 확인: `GET /llm/v1/models`
- 질문 실행: `POST /llm/v1/ask`

EC2에서도 같은 명령을 사용하고 SSH 터널로 접속할 수 있다: `ssh -L 8011:127.0.0.1:8011 user@EC2_HOST`. 외부 바인딩이 필요하면 `--host 0.0.0.0`과 `LLM_V1_API_KEY`를 설정하고 HTTPS 프록시·보안그룹으로 접근 범위를 제한한다. Swagger의 Authorize에 API 키를 입력한다. 기본 localhost 모드는 키 없이 사용한다.

```json
{
  "question": "이 제품의 효능을 알려주세요.",
  "products": ["DB에 저장된 실제 제품명"],
  "model": "haiku"
}
```

`intent` 입력은 제거했다. `products`는 OCR에서 받은 **제품명 문자열 배열**(최대 8개)이다. 질문에 제품명이 있으면 생략하거나 빈 배열로 보낼 수 있다. 질문 속 제품명과 목록을 합쳐 최대 8개를 처리한다. 제품 유형·ID 입력은 필요 없다. 모델은 `haiku` 또는 `sonnet`이며 생략하면 기본 모델을 사용한다.

```json
{
  "question": "이 두 제품의 효능과 함께 먹을 때 주의사항을 알려주세요.",
  "products": ["첫 번째 제품명", "두 번째 제품명"],
  "model": "sonnet"
}
```

서버는 질문 속 제품명과 OCR 제품명을 합쳐 중복을 제거한다. 이름은 gold에서 정확 일치로만 확인한다. 미등록/모호한 이름이 있으면 후보 검색·선택 목록을 제공하지 않고, 해당 원래 이름들을 LLM에 전달하여 정확한 제품명·제조사·함량을 부드럽게 다시 요청한다. 다른 제품을 추측해서 설명하지 않는다. 이전 `selections`, `name_selections` 입력은 제거했다.

응답은 아래 세 필드만 반환한다. 아래 answer는 문체 예시이며 실제 문장은 LLM이 생성한다.

```json
{
  "status": "needs_clarification",
  "answer": "‘입력하신 이름’만으로는 정확한 제품을 확인하기 어려워요. 포장에 적힌 전체 제품명과 제조사, 함량을 알려주시면 다시 확인해 드릴게요.",
  "usage": {"routing": {}}
}
```

- `status`: answered / needs_clarification / insufficient_data / refused / error.
- `answer`: 제품 정보·병용 안내·미확정 이름·자료 부족 등을 LLM이 사용자 친화적인 존댓말로 정리한다. 내부 코드·근거 ID·후보는 표시하지 않는다.
- `usage`: `routing`에 분류/추출 호출의 Bedrock 사용량만 반환한다. 답변 생성 및 임베딩 호출 사용량은 포함하지 않는다.

재확인 안내도 LLM을 사용한다. 모델 거절·응답 잘림·서비스 오류 시에는 생성 답변을 사용할 수 없어 고정된 친절한 오류 안내를 반환한다. HTTP 오류 코드(401/422/503)는 유지하며 본문도 status/answer/usage 형식이다. 분류 호출은 최대 500 출력 토큰, 답변 호출은 기본 900 출력 토큰이다. 실제 문체/추출 품질은 모델 평가가 필요하다.

## 데이터 연결

DB 연결은 `database.py`에서 관리하며 `DATABASE_URL`, `LLM_V1_DATABASE_URL` 등 DB 환경변수를 읽지 않는다.

| 항목 | 설정 |
| --- | --- |
| 리전 | us-east-1 |
| 호스트 | Secrets Manager `pill-check/dev/app`의 `DB_HOST` |
| 포트 / DB | 5432 / pill |
| 시크릿 이름 | rds!db-71cf9992-e13e-4601-88da-425ac219f336 |
| 인증 | EC2 역할로 Secrets Manager 조회 후 username/password로 PostgreSQL 접속 |

RDS 자격증명 시크릿의 `username`, `password`와 앱 시크릿 `pill-check/dev/app`의 `DB_HOST`를 읽는다. DB명과 포트는 위 설정을 유지한다. 호스트 하드코딩이나 환경변수 대체 경로는 없으며 DB_HOST가 없거나 비어 있으면 연결을 중단한다. 비밀번호를 URL·파일·로그에 기록하지 않는다. 새 물리 연결마다 두 시크릿의 `AWSCURRENT`를 읽으며 기존 풀 연결은 재사용한다. 연결은 300초 이후 재사용 시 교체하여 비밀번호·호스트 변경에 대응한다. 이는 RDS IAM DB 토큰 인증과는 다른, Secrets Manager 기반 비밀번호 인증이다.

EC2 역할에 `iam/rds-secret-policy.template.json`의 권한을 추가한다. `<AWS_ACCOUNT_ID>`를 실제 계정 ID로 바꾸고 가능하면 Resource를 콘솔의 완전한 시크릿 ARN으로 교체한다. 마지막 `-??????`는 AWS 시크릿 ARN의 6자리 접미사다. 고객 관리 KMS 키로 암호화했다면 해당 키의 `kms:Decrypt` 권한 및 키 정책 허용도 필요하다. 이 정책은 자동 적용하지 않는다. 시크릿이 RDS 관리형 master 사용자라면 해당 사용자의 DB 권한으로 접속하게 된다.

EC2에서 Secrets Manager HTTPS 접근 및 RDS 5432 접근이 가능해야 한다. RDS 보안그룹에서 EC2 보안그룹의 접근을 허용한다. `certs/us-east-1-bundle.pem`은 [AWS 공식 RDS CA 번들](https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem)이며 TLS 인증서와 호스트명을 검증한다. CA 변경 시 공식 번들로 갱신한다.

EC2의 backend 디렉터리에서 읽기 전용 연결 확인:

```bash
python -m app.llm.v1.check_database
```

성공하면 `{"connected": true, "database": "pill"}`을 출력한다. 비밀번호를 출력하거나 테이블을 생성하지 않는다. 이 검사는 네트워크/인증 연결만 확인하며 아래 벡터 스키마와 데이터는 별도로 준비해야 한다.

AWS 참고: [GetSecretValue 권한](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html), [RDS 관리형 시크릿](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html).

현재 ask는 **gold와 pgvector를 함께 사용**한다. 제품 확정·의약품 DUR·건기식 섭취 주의사항은 gold를 기준으로 한다. 벡터 DB는 확정 제품의 정보 검색과 의약품끼리의 병용에서 보조 상호작용 원문 검색에 사용한다. 제품명 후보 검색에는 사용하지 않는다. 요청 전체는 repeatable-read/read-only 트랜잭션에서 처리하며 `gold.load_info`로 적재 버전을 표시한다. 실제 gold 테이블이 적재되어 있어야 한다. 런타임 계정에 gold 및 product_search 스키마 USAGE/테이블 SELECT 권한이 필요하다. 벡터 모델·차원이 설정과 일치하고 공개된 벡터 snapshot 날짜가 gold와 같아야 한다. 벡터가 미준비/미공개/다른 snapshot이면 확인된 gold 자료만 사용하며 필요한 제한 사항은 LLM 답변에 쉽게 설명한다. 네트워크·권한 등 실행 오류는 정상 fallback으로 숨기지 않는다.

| 목적 | 원본 |
| --- | --- |
| 제품 이름·유형 | gold.drug / gold.health_food |
| 의약품 효능·용법·주의 | doc_efficacy, doc_dosage, doc_precautions 및 easy_* |
| DUR 주의 조건 | gold.drug_dur_caution 원문 전체 (조건별 복수 포함) |
| 의약품 성분 | gold.drug_ingredient.ingr_key, ingr_name, dur_ingr_code |
| 병용 규칙 | gold.drug_contraindication |
| 건기식 기능성·섭취 방법·주의 | primary_fnclty, ntk_mthd, iftkn_atnt_matr_cn |

Python이 각 의약품쌍의 성분과 DUR 코드를 읽고, 해당 제품쌍의 금기 규칙을 조회해 양방향으로 비교한다. gold 금기 테이블은 이미 제품쌍에 제형·복합제 조건을 적용한 데이터이므로 **다른 제품의 동일 성분 규칙을 가져와 적용하지 않는다**. 내부 `code_match`에 양쪽 성분 코드 비교 결과를 기록한다. 복합 코드 또는 매핑 누락 때문에 code_match가 false여도 정확한 제품쌍의 품목 DUR를 버리지 않는다.

- `basis=품목 DUR` → `contraindicated`: 공식 제품쌍 금기 확인.
- `basis=성분 규칙` → `ingredient_caution`: 성분 기준 주의. 공식 품목 금기로 격상하지 않는다.
- 규칙 없음 + 코드 누락/판매중지 → `unknown`.
- 조회 조건이 충족되지만 규칙 없음 → `not_found`. 병용 안전 보장은 아니다.
- `ingr_key`가 같으면 내부 `duplicate_ingredients`에 기록하고 답변에서 설명한다. 동일 성분 중복을 금기라고 단정하지 않는다.

성분 매핑 여부는 조회 범위의 상태일 뿐 의료 데이터 전체의 완전성을 인증하지 않는다. `remark`, `notification_date`, `carried_from`, 원문 및 출처를 보존한다. 건기식이 포함된 병용은 건기식의 섭취 시 주의사항 원문을 추가한다. 건기식 상호작용을 추정하거나 의약품 DUR 판정으로 취급하지 않는다.

이전 `load_safety.py`, `sql/safety.sql`, SafetyBundle, 기존 compare 함수는 과거 계약 호환을 위해 남겨두었지만 **현재 ask에서는 사용하지 않는다**. 별도 llm_v1 금기 테이블이나 JSON 적재가 필요 없다. gold 데이터는 기존 파이프라인이 관리하며 이 모듈은 수정하지 않는다.

## 백엔드 호출

백엔드 `app/main.py`가 v1 전용 앱을 `/api/llm/v1`에 mount하고, 부모 lifespan에서 자식 앱의 초기화·종료를 수행한다. 기존 Nginx `/api/` 프록시를 그대로 사용한다. 메인 백엔드 Swagger와 별도로 v1 Swagger를 제공하며, 메인 앱의 prod Swagger 비활성화 설정과 무관하게 v1 docs는 열린다.

- 별도 Swagger: http://ec2-54-197-92-156.compute-1.amazonaws.com/api/llm/v1/docs
- OpenAPI: `/api/llm/v1/openapi.json`
- 모델 목록: `GET /api/llm/v1/models`
- 질문: `POST /api/llm/v1/ask`

변경된 코드를 EC2에 반영한 뒤 `deploy/ec2`에서 `docker compose up -d --build backend`로 재배포한다. 이 경로에는 별도 llm-v1 컨테이너가 필요 없다. 백엔드 컨테이너가 EC2 역할·Secrets Manager·RDS·Bedrock에 접근할 수 있어야 한다. Swagger의 Try it out도 위 mount 경로를 사용한다. `LLM_V1_API_KEY`를 설정했다면 Authorize에 입력한다.

기존 독립 실행(`app.llm.v1.api:app`)은 계속 `/docs`, `/llm/v1/ask`, `/llm/v1/models`를 제공한다. 직접 Python 호출은 `Service(Repository(connection, settings), Bedrock(settings), settings).ask(AskRequest(...))`를 사용하며 connection은 PostgreSQL repeatable-read/read-only 트랜잭션이어야 한다.

## IAM 및 모델

기본 `LLM_V1_AUTH_MODE=ec2_role`은 boto3가 얻은 자격증명의 출처가 EC2 instance profile(`iam-role`)인지 확인한다. 다른 환경변수 키/공유 프로필 등이 먼저 선택되면 명시적으로 실패한다. 자격증명 갱신은 SDK에 맡기고 SigV4로 서명한다. 코드에 AWS 키를 저장하지 않는다. 로컬 프로필·SSO 테스트에만 `LLM_V1_AUTH_MODE=default_chain`을 사용한다. 이 모드도 SigV4이며 Bedrock bearer API 키 인증은 사용하지 않는다.

전달받은 `BedrockAPIKey-wy45`는 **IAM 사용자 이름**이다. 이 사용자를 EC2에 연결하거나 사용자 이름을 `AWS_PROFILE`, 역할 ARN, 모델 ID에 넣지 않는다. 인프라 담당자는 Bedrock 권한을 가진 **EC2용 IAM 역할 및 instance profile**을 생성하여 EC2에 연결해야 한다. 사용자의 권한은 역할에 자동 상속되지 않는다. 역할 이름은 코드 설정에 필요하지 않으며 실제 연결된 역할을 SDK가 발견한다. 콘솔 URL의 `us-east-1`을 초기 Bedrock 리전으로 사용하되, IAM 사용자는 리전 전용 리소스가 아니므로 실제 Bedrock 사용 리전은 인프라 구성과 맞춰야 한다.

인프라 전달용 파일(이 코드가 AWS에 자동 적용하지 않음):

- `iam/ec2-trust-policy.json`: 역할의 EC2 신뢰 정책.
- `iam/bedrock-invoke-policy.template.json`: 역할의 Bedrock 호출 권한 예시. `<AWS_ACCOUNT_ID>`를 실제 계정 ID로 교체해야 한다. 기본 us-east-1/US 프로필용이며 리전·프로필을 바꾸면 정책 ARN도 변경한다. `us-*`는 US 교차 리전 대상 모델을 허용하며, 인프라 정책에 따라 확인된 대상 리전을 개별 나열해 더 좁힐 수 있다.

Claude inference profile 및 대상 foundation-model 리소스, Titan embedding 모델에 `bedrock:InvokeModel` 권한이 필요하다. 교차 리전 프로필 사용 시 대상 리전 권한과 조직 SCP도 확인한다. 모델 최초 활성화/Marketplace 구독이 필요하면 배포 관리자 계정에서 준비한다. 런타임 역할에 사용자 관리 권한을 줄 필요는 없다. API는 Converse, 임베딩은 InvokeModel을 사용한다. 프로필 ID/ARN은 환경변수로 교체 가능하며 임의 모델을 HTTP 입력으로 받지는 않는다.

EC2 프로세스에 정적 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, 불필요한 `AWS_PROFILE` 또는 `AWS_BEARER_TOKEN_BEDROCK`을 주입하지 않는다. IMDS는 활성화하고 IMDSv2 사용을 권장한다. EC2 내부 Docker에서 실행하면 컨테이너도 IMDS에 도달하도록 인프라에서 네트워크/hop limit을 구성해야 한다. SDK가 Bedrock/STS HTTPS 엔드포인트에 접근할 네트워크 경로도 필요하다.

EC2의 backend 디렉터리에서 다음 명령으로 DB 없이 인증·추론을 확인한다:

```bash
# 역할 출처 확인 및 STS 호출자 ARN 출력. Bedrock 권한 검증은 아직 아님.
python -m app.llm.v1.check_bedrock
# 실제 유료 호출: Titan 임베딩 1회, Haiku 1회, Sonnet 1회
python -m app.llm.v1.check_bedrock --invoke
```

첫 명령의 `caller_arn`이 기대하는 `arn:aws:sts::...:assumed-role/실제역할이름/...`인지 확인한다. 두 번째 명령이 성공해야 `inference_verified=true`다. 실패 시 종료 코드는 1이며 비밀 키는 출력하지 않는다. `LLM_V1_API_KEY`는 Swagger/자체 HTTP API 접근용이며 AWS 인증 키와 무관하다.

역할/인증 참고: [EC2 역할 연결](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_switch-role-ec2.html), [Boto3 자격증명](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html).

AWS 공식 문서에서 확인한 모델 ID를 기본 설정으로 사용한다(2026-10-16). 지역별 지원은 계정에서 재확인한다:

- https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-titan-text-embeddings-v2.html

## 토큰·정확성 및 테스트

일반적인 '약품에 대해 설명해줘' 요청은 내부 overview 모드로 분류해 제품별 용도·효능을 1~2문장으로 소개한다. 질문과 products 목록을 합쳐 중복을 제거하고, Gold 효능 원문과 제품별 벡터 효능 근거를 조회한다. 제품마다 입력 예산을 나누고 짧은 `gold.drug.easy_efcy`를 우선하며 문서 중간을 자르지 않는다. 긴 주의사항 전체는 일반 소개에 자동으로 추가하지 않는다. 답변은 상세 용법·주의사항 및 병용 안전 판정이 아닌 소개임을 안내한다. 일부 제품의 근거가 없거나 예산 안에 들어가는 문서가 없으면 해당 제품을 구분하고 나머지 제품의 확인된 소개를 유지한다. 구체적인 주의사항·부작용·환자 조건·병용 질문은 기존 상세 조회 경로를 사용한다. 외부 요청/응답 필드는 동일하다.

질문 추출/분류 1회, 사용자 답변 생성 1회를 사용한다. 답변 생성이 `max_tokens`로 종료된 경우에만 같은 원문 근거로 간결한 재작성을 1회 추가한다. 추가 호출은 기존 출력 토큰 한도를 유지하며 비용·응답 시간이 늘어날 수 있다. 재작성도 미완료면 부분 답변을 공개하지 않는다. 거절 응답은 재시도하지 않는다. 외부 usage는 재작성 여부와 관계없이 routing만 제공한다.

답변은 결론부터 간결하게 전달하고 반복 안내를 줄이되 금기 조건·예외·확인 한계를 보존하도록 지시한다. 확인 요청에는 확정 제품명과 미확정 이름을 구분하여 전달하고 미확정 이름만 다시 묻도록 한다. 질문에 언급됐더라도 문의 대상에서 제외된 제품은 조회했다고 주장하거나 답변에 재언급하지 않도록 한다. 이 표현 규칙의 실제 모델 준수 여부는 배포 후 검증해야 한다.

모든 제품이 확정된 경우에만 벡터와 의료 근거를 조회한다. 벡터는 확정 제품/자료 유형/공개 run으로 범위를 제한하며 질문 임베딩을 재사용한다. 주의사항 원문은 임의로 자르지 않는다. 입력 예산 초과는 LLM이 제품 수나 질문 범위를 줄이도록 안내한다.

의약품 간 비교 결과·원문·조건은 내부 프롬프트에 남기되 외부 응답에는 status/answer/usage만 보낸다. 의약품 1개와 건강기능식품 1개는 성분 비교 없이 gold.health_food.iftkn_atnt_matr_cn 전체를 사용한다. 이 원문이 없으면 상호작용을 만들어내지 않고 부족한 자료를 설명한다.

프로젝트 루트에서 AWS/DB 실제 호출 없는 회귀 테스트:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='backend'
python -m unittest discover -s backend/app/llm/v1/tests -v
```

실제 EC2/Bedrock/RDS 연결과 모델 답변 품질은 별도 검증이 필요하다. 변경 코드를 EC2에 반영한 뒤 deploy/ec2에서 `docker compose up -d --build backend`로 재배포한다.

## 제품쌍 판정과 성분 단위 보완 조회

의약품만 포함된 병용 전용 질문은 `grounded_answer.py`로 검증된 사실 블록을 만든다. LLM은 블록 제목을 보고 표시 순서만 JSON으로 제안하고, 모든 ID가 정확히 한 번씩 있는 경우에만 적용한다. 자유 생성 문장이나 누락·중복·잘린 응답은 사용하지 않고 기본 순서로 완전한 사실을 표시한다. 금기 원문/예외·성분 확인 범위·중복 이름·제형별 성분 용량 참고를 Python 결과에서 직접 표시하므로 임의 약물 분류나 복용 변경 권고를 추가하지 않는다. 용량 참고는 제품의 투여량으로 연결하지 않는다. 설명서 보조 근거가 있으면 원문 전체를 유지하므로 답변이 길어질 수 있다. 효능과 병용을 함께 묻는 질문, 건기식 조합은 기존 생성 경로이며 동일한 보장이 적용되지 않는다. 응답 필드와 usage.routing 계약은 유지한다.

이미 열려 있는 SSM 포트로 읽기 전용 진단: 프로젝트 루트에서 PYTHONPATH=backend를 설정하고 `python backend/app/llm/v1/evaluations/probe_ssm_gold.py --port 5432`를 실행한다. 로컬 AWS 기본 자격증명으로 시크릿을 읽고 RDS 호스트명을 TLS 검증에 사용하며 접속 주소만 127.0.0.1 터널로 지정한다. psycopg가 설치된 로컬 진단 환경용이며 서비스 의존성을 변경하지 않는다. 결과에는 의약품 데이터만 저장하며 자격증명은 출력하지 않는다. DB나 벡터 적재는 수정하지 않는다.

제품쌍별 `pair_explanation`은 Python이 제품 금기 조회 결과, 성분 비교 범위, 서로 다른 D코드 조합 비교 수, 동일 성분 중복을 따로 만든다. 비교 범위는 일부 비교/조회 성분 코드 전체 비교/비교 불가/동일 코드뿐이라 서로 다른 성분 조합 없음으로 구분한다. 세 제품 중 한 쌍만 일부 비교한 결과를 세 제품 전체 비교 불가로 합쳐 표현하지 않도록 프롬프트에 전달한다. 실제 제품의 모든 성분을 검증하거나 안전을 보장한다는 의미는 아니다. 성분 코드가 없는 행에는 정확한 이름의 코드 미발견, 다중 코드, 성분명 부재를 기록하고 근거 없이 코드를 추정하지 않는다. 응답 status=answered는 조회 결과 안내 완료이며 병용 안전 판정이 아니다. 외부 응답 필드는 유지한다.

벡터의 제품 연결 테이블 `product_search.product_links`에는 의약품 `item_seq`가 `source_product_id`에 저장되고, `product_key`는 `drug:{item_seq}`다. 벡터 본문 테이블은 여러 제품이 공유할 수 있으므로 제품 ID는 links에서 확인한다. 런타임은 확정한 gold 제품의 product_key로 검색 범위를 제한한다. 이는 적재 코드의 계약이며 실제 서버 적재 여부는 별도로 확인해야 한다.

첨부된 성분 판정 쿼리를 참고하여 다음을 각각 수행한다.

1. gold.drug에서 확정한 제품 ID로 제품쌍 DUR를 조회한다.
2. gold.drug_ingredient에서 제품별 성분/D코드를 가져온다. D코드가 없으면 동일한 성분명으로 다른 행의 매핑을 조회하되 코드가 하나일 때만 보완한다. 다중 매핑은 임의 선택하지 않는다.
3. 입력 성분 코드들로 gold.drug_contraindication을 집계한다. 2026-10-23 쿼리에 맞춰 `ingr_code < mixture_ingr_code`로 서로 다른 성분의 한 방향만 집계하며 품목 DUR 행 존재 여부, 성분 규칙 행 수, 원문, 비고를 유지한다. 동일 D코드의 제품 간 중복은 Python에서 별도로 판정한다.
4. Python에서 서로 다른 제품 사이의 성분 조합만 비교한다. 한 제품 내부의 성분 두 개를 두 제품 간 금기로 잘못 적용하지 않는다.
5. 제품쌍 결과와 성분 단위 결과를 구분하여 프롬프트를 만든다. 다른 제품쌍에서 발견한 성분 규칙은 현재 제품의 공식 금기로 격상하지 않는다. 제형/투여경로/복합제 적용 여부가 남는다.
6. 제품별 easy_intrc 원문과 해당 product_key의 벡터 interactions 문서를 보조 근거로 사용한다. 벡터가 없다고 gold 판정이 무효가 되지는 않는다.

2026-10-23 적재본의 `gold.drug.route`와 `gold.dur_ingredient_rule`도 사용한다. 새 테이블은 `mix_type='단일'` 규칙만 조회한다. Python이 서로 다른 제품의 서로 다른 D코드가 같은 sers_name에 속하는지 비교하고, 양쪽 제품이 모두 경구로 확인된 경우에만 효능군 '중복 주의'를 만든다. 경로 미확인·경구 외는 효능군 중복 미발견으로 단정하지 않는다. 용량주의는 경구 외 규칙/제품을 제외하되 null 경로는 미확인 참고 자료로 유지한다. max_qty 원문과 모든 제형·경로를 보존하며 개인 권장량·제품 복용량이나 용량 초과 판정으로 사용하지 않는다. 동일 성분 중복·효능군 중복·제품쌍 금기·성분 기준 금기는 각각 구분한다. 새 테이블 SELECT 권한이 필요하며 테이블 부재/권한 오류를 금기 미발견으로 숨기지 않는다. 의약품 1개+건기식 조합은 기존 섭취 주의사항 경로를 유지한다.

답변은 해당 제품쌍에서 금기가 확인됐는지 먼저 설명하고, 성분 기준 조회 결과와 미매핑 성분/조회 수를 구체적으로 구분한다. D코드 없음은 위험/안전 또는 성분 자체 없음의 증거가 아니다. 조회가 완료되어 제품쌍 금기 미발견을 설명할 수 있으면 status는 answered일 수 있으며 이는 **병용 안전 판정이 아니라 조회 결과 안내 완료**를 뜻한다. 데이터 접근 실패는 error, 필요한 효능/건기식 주의 원문 등이 없으면 insufficient_data로 처리한다.

현재 gold에는 판매 제품쌍으로 펼쳐지지 않은 silver 성분 원본 규칙이 없으므로 그 규칙까지 조회했다고 주장하지 않는다. 전체 입력 예산 초과 시 조건을 잘라 답하지 않고 질문 범위 축소를 요청한다. 약-건기식 조합은 계속 건기식 섭취 주의사항으로 설명하고 성분 DUR를 적용하지 않는다.

성분 확인 범위는 Python이 제품별 `mapping_coverage.mapping_state`와 `explanation`으로 생성한다. 성분 자료 없음, 비교 연결 0개, 일부 연결, 조회 성분 모두 연결을 구분하고 조회 개수·연결 개수를 문장에 고정한다. LLM은 해당 문장의 수치와 의미를 유지하며 서로 다른 제품 상태를 하나로 일반화하지 않도록 지시받는다. 연결 가능은 실제 비교 완료나 안전 판정이 아니며, 조회 성분 전체가 제품의 전체 성분이라는 뜻도 아니다. 이 설명 보강은 기존 제품쌍 DUR 판정과 조건·예외를 변경하지 않는다. 실제 생성 답변의 준수 여부는 배포 후 재검증이 필요하다.

질문 분류의 내부 필드 `excluded_product_names`는 문의에서 명시적으로 제외된 이름을 담는다. 원문에 없는 이름이나 문의/제외 목록 간 충돌은 분류 실패로 처리한다. Python은 제외 이름을 답변 생성용 질문 및 벡터 검색 질문에서 중립 표식으로 치환하고 환자 조건과 나머지 문장은 유지한다. 분류 호출에만 원래 질문을 전달하며 추가 모델 호출은 없다. 명시적 products 목록에 있는 이름은 유지하고, 긴 문의 제품명 안에 포함된 짧은 제외 이름을 잘못 치환하지 않는다. 아직 복용하지 않아도 향후 복용이나 효능을 질문하는 제품은 제외 대상이 아니다. 제외 여부 추출 자체는 모델에 의존하므로 배포 후 반복 검증이 필요하다. 외부 요청/응답 스키마는 바뀌지 않는다.

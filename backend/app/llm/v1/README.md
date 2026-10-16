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
  "question": "이 제품의 효능을 알려주세요",
  "intent": "efficacy",
  "products": [{"name": "DB에 저장된 정확한 제품명", "product_type": "drug"}],
  "model": "haiku"
}
```

병용 질문은 `intent: "interactions"`와 서로 다른 제품 2~8개를 넣는다. 건강기능식품은 `product_type: "health_food"`다. `model`만 `sonnet`으로 변경해 같은 질문의 답변, `usage`, `latency_ms`를 비교한다. 모델 접근 권한·리전별 실제 품질/비용/속도는 EC2에서 확인해야 한다. 자동 모델 전환은 없으며 선택한 모델 실패를 그대로 알린다.

유사 이름·동일 이름 복수 후보·미등록 제품은 `needs_clarification`으로 반환한다. 후보의 제조사와 제품명을 사용자에게 확인받고 해당 입력에 `product_key`를 추가하여 전체 요청을 다시 보낸다. 이름 검색은 정확 일치 → 부분/철자 유사 후보 검색이며, 유사 후보를 자동 확정하지 않는다. 서버가 대화 상태를 저장하지 않는다. 백엔드에서 사용자 자연어를 전달할 때도 `intent`, 제품 목록을 함께 제공해야 한다.

## 데이터 연결

DB 연결은 `database.py`에서 관리하며 `DATABASE_URL`, `LLM_V1_DATABASE_URL` 등 DB 환경변수를 읽지 않는다.

| 항목 | 설정 |
| --- | --- |
| 리전 | us-east-1 |
| 호스트 | pill-check-dev-postgres.c43ekyi6yiie.us-east-1.rds.amazonaws.com |
| 포트 / DB | 5432 / pill |
| 시크릿 이름 | rds!db-71cf9992-e13e-4601-88da-425ac219f336 |
| 인증 | EC2 역할로 Secrets Manager 조회 후 username/password로 PostgreSQL 접속 |

시크릿 JSON의 `username`, `password`를 읽고 호스트/DB는 위 설정을 사용한다. 비밀번호를 URL·파일·로그에 기록하지 않는다. 새 물리 연결마다 `AWSCURRENT`를 읽으며 기존 풀 연결은 재사용한다. 연결은 300초 이후 재사용 시 교체하여 비밀번호 회전에 대응한다. Secrets Manager가 실패하면 환경변수 비밀번호로 대체하지 않는다. 이는 RDS IAM DB 토큰 인증과는 다른, Secrets Manager 기반 비밀번호 인증이다.

EC2 역할에 `iam/rds-secret-policy.template.json`의 권한을 추가한다. `<AWS_ACCOUNT_ID>`를 실제 계정 ID로 바꾸고 가능하면 Resource를 콘솔의 완전한 시크릿 ARN으로 교체한다. 마지막 `-??????`는 AWS 시크릿 ARN의 6자리 접미사다. 고객 관리 KMS 키로 암호화했다면 해당 키의 `kms:Decrypt` 권한 및 키 정책 허용도 필요하다. 이 정책은 자동 적용하지 않는다. 시크릿이 RDS 관리형 master 사용자라면 해당 사용자의 DB 권한으로 접속하게 된다.

EC2에서 Secrets Manager HTTPS 접근 및 RDS 5432 접근이 가능해야 한다. RDS 보안그룹에서 EC2 보안그룹의 접근을 허용한다. `certs/us-east-1-bundle.pem`은 [AWS 공식 RDS CA 번들](https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem)이며 TLS 인증서와 호스트명을 검증한다. CA 변경 시 공식 번들로 갱신한다.

EC2의 backend 디렉터리에서 읽기 전용 연결 확인:

```bash
python -m app.llm.v1.check_database
```

성공하면 `{"connected": true, "database": "pill"}`을 출력한다. 비밀번호를 출력하거나 테이블을 생성하지 않는다. 이 검사는 네트워크/인증 연결만 확인하며 아래 벡터 스키마와 데이터는 별도로 준비해야 한다.

AWS 참고: [GetSecretValue 권한](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html), [RDS 관리형 시크릿](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html).

기존 `vector_pipeline`으로 pgvector 스키마 v2를 생성하고 전체 snapshot을 publish해야 한다. `product_search.pipeline_config`의 임베딩 모델/차원/version이 일치해야 한다. 제품 선택 후 해당 제품의 `benefits`를 Titan V2 임베딩으로 순위 검색한다. 건강기능식품 병용은 해당 제품 `precautions` 전체를 읽는다. 한 질문은 repeatable-read 트랜잭션에서 하나의 run_id만 조회한다.

기존 파이프라인의 성분·DUR 자료는 silver Parquet이고 현재 백엔드에는 실제 병용금기 SQL 테이블이 없다. 따라서 추가 계약 `llm_v1.product_ingredients`, `llm_v1.contraindication`을 제공한다. 자동 성분명 추측이나 허가 원료 코드(mtral_code)를 DUR 코드로 간주하지 않는다. 실제 운영 전 검증된 **동일 DUR 코드 체계 매핑**과 금기 자료를 다음 JSON으로 준비한다. 아래 값은 형식 설명용이며 의료 데이터가 아니다.

```json
{
  "run_id": "vector_pipeline의 완료된 실제 run_id",
  "code_system": "DUR",
  "rules_complete": false,
  "source": "원본 자료 식별자 및 버전",
  "products": [
    {"product_key":"drug:실제품목ID1","codes":["DUR_CODE_A"],"complete":false,"source":"검증된 매핑 출처"},
    {"product_key":"drug:실제품목ID2","codes":["DUR_CODE_B"],"complete":false,"source":"검증된 매핑 출처"}
  ],
  "rules": [{
    "rule_id":"원본 규칙 ID","left_codes":["DUR_CODE_A"],"right_codes":["DUR_CODE_B"],
    "content":"병용금기 원문 전체","conditions":"제형·용량·대상 등 조건 및 예외 원문",
    "source":"원본 규칙 출처 및 고시일"
  }]
}
```

JSON을 v1 아래에 저장한 뒤 backend 디렉터리에서 `python -m app.llm.v1.load_safety app/llm/v1/safety-bundle.json`을 실행한다. DDL/INSERT 권한이 있는 적재 계정이 필요하다. CLI는 트랜잭션으로 테이블 생성·제품 존재 확인·적재를 수행한다. 동일 run 재적재는 덮어쓰지 않고 실패한다. 런타임 계정에는 두 스키마 USAGE와 테이블 SELECT만 부여한다. 실제 DB에 이 작업을 자동 실행하지는 않는다.

원본 `dur_contraindication`의 `level=성분`, `is_rule_valid=true`인 유효 규칙에서 좌우 DUR 코드를 준비한다. 복합 성분 배열은 **모든 성분이 함께 있어야 하는 조합**으로 비교된다. OR 대안은 별도 규칙 ID로 분리해야 한다. 원문의 조합·삭제 상태·조건을 검증하지 못하면 변환하지 않는다. `level=품목` 규칙은 이 성분 비교 계약의 지원 범위 밖이며, 해당 제약을 포함한 전체 커버리지가 검증되지 않았다면 `rules_complete=false`를 유지한다. 제품별 `complete`도 전 성분의 매핑을 확인한 경우에만 true로 설정한다. 이 코드에는 silver 원본에서 검증된 DUR 매핑을 자동 생성하는 기능이 없다.

Python이 각 의약품 쌍의 성분 집합을 양방향으로 비교한다. 조건 없는 일치=`contraindicated`, 조건 있는 일치=`conditional`, 완전한 조회에서 미발견=`not_found`, 불완전=`unknown`이다. 조건의 적용 여부는 자동 판단하지 않는다. 빈 DB·누락 성분·다른 snapshot은 안전 판정으로 처리하지 않는다. 약-건기식 및 건기식-건기식은 건기식 주의사항만 설명하며 정식 금기 판정은 제공하지 않는다.

## 백엔드 호출

독립 서비스의 `/llm/v1/ask`를 기존 백엔드에서 HTTP로 호출하거나 `Service(Repository(connection, settings), Bedrock(settings), settings).ask(AskRequest(...))`를 호출한다. 직접 호출 시 connection은 PostgreSQL repeatable-read/read-only 트랜잭션이어야 한다. 독립 앱의 `lifespan`과 `router`를 재사용할 수도 있지만 기존 백엔드에 router만 추가하면 필요한 app.state가 없으므로 작동하지 않는다. 현재 변경 범위 제한 때문에 기존 main.py에는 라우터를 등록하지 않았다.

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

확인 질문은 LLM 호출 없이 반환한다. 제품 목록·질문을 명시 입력으로 받아 별도 추출 LLM 호출을 없앴다. 기본 효능 검색은 제품당 3개, 출력은 900토큰, 프롬프트는 18,000자 예산이다. 문자 예산은 정확한 토큰 수가 아니며 실제 값은 Bedrock `usage`로 확인한다. 주의사항/금기 조건은 임의로 잘라내지 않는다. 예산 초과 시 범위를 줄이도록 안내한다. 거리 임계값 0.65는 초기 설정이며 실제 평가 데이터로 조정해야 한다. 효능은 검색된 근거 일부에 대한 설명이며 전체 허가사항 요약을 보장하지 않는다.

응답의 `interaction_checks`, `evidence`, `warnings`를 답변과 함께 UI에 표시한다. 모델의 자연어 설명은 확률적이므로 구조화된 Python 판정이 기준이다. 거절·출력 길이 초과·미완료 답변은 정상 답변으로 반환하지 않는다. 근거 없음을 모델 지식으로 채우지 않는다.

프로젝트 루트에서 외부 AWS/DB 호출 없는 회귀 테스트:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='backend'
python -m unittest discover -s backend/app/llm/v1/tests -v
```

실제 환경에서는 동일 질문을 두 모델로 실행하여 출처 일치, 금기 조건 보존, 토큰 및 지연을 비교한다. 이번 로컬 테스트는 실제 Bedrock 권한, DB 적재 여부 또는 임상 정확성을 인증하지 않는다.

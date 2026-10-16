# 약·건강기능식품 LLM v1

이 디렉터리만으로 실행하는 FastAPI / Bedrock RAG 모듈이다. 모델 학습이 아니라 기존 제품 DB와 Claude를 연결한다. 기존 백엔드 파일은 변경하지 않는다.

## 실행 및 Swagger

기존 backend/pyproject.toml의 의존성(fastapi, uvicorn, sqlalchemy, asyncpg, boto3, pydantic-settings)이 설치된 Python 3.12 환경을 사용한다. 프로젝트 루트에서:

```powershell
Copy-Item backend/app/llm/v1/.env.example backend/app/llm/v1/.env
python -m uvicorn app.llm.v1.api:app --app-dir backend --host 127.0.0.1 --port 8011
```

`backend/app/llm/v1/.env`에 실제 DB URL과 Bedrock 리전을 설정한다. 기존 backend/.env와 다른 독립 설정이다. 비밀번호는 URL 인코딩하고 .env를 커밋하지 않는다.

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

EC2 instance profile을 boto3 기본 credential chain으로 사용한다. 코드에 AWS 키를 저장하지 않는다. Claude inference profile 및 대상 foundation-model 리소스, Titan embedding 모델에 `bedrock:InvokeModel` 권한이 필요하다. 교차 리전 프로필 사용 시 대상 리전 권한과 조직 SCP도 확인한다. API는 Converse, 임베딩은 InvokeModel을 사용한다. 프로필 ID/ARN은 환경변수로 교체 가능하며 임의 모델을 HTTP 입력으로 받지는 않는다.

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

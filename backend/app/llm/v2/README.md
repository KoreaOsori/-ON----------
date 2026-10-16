# llm/v2 — 약 정보 RAG 챗봇 (도구 호출 루프 직접 구현)

이 폴더 **안에서만** 동작하도록 만들었습니다. `backend/pyproject.toml`, `app/core`, `vector_pipeline` 등 바깥 파일은 수정하지 않았고,
새 의존성도 추가하지 않았습니다(기존 `anthropic[bedrock]`, `boto3`, `sqlalchemy[asyncio]`, `asyncpg`만 사용).
langchain/langgraph 없이 anthropic SDK의 `tools` 기능으로 루프를 직접 돌립니다.

```
질문 ─▶ answer() ─▶ [모델 호출 ─▶ tool_use? ─▶ search_drug_info 실행 ─▶ tool_result] ×최대 N회 ─▶ 최종 답변
                          └ 한도·허용 도구·근거 검사는 코드가 강제 (모델 출력에 맡기지 않음)
```

## 파일 구성 (강의 코드와의 대응)

| 파일 | 역할 | 강의 대응 |
|---|---|---|
| `agent.py` | 도구 호출 루프, 외부 진입점 `answer(question, profile_context, product_key)` | `graph.py` |
| `harness.py` | `Limits`(라운드/호출/시간), `Budget`, `ALLOWED_TOOLS` | `harness.py` |
| `tools.py` | `search_drug_info` 도구 정의·실행·`[출처 \| 제품명 \| 섹션]` 포매터 | `tools/rag_tools.py` |
| `search.py` | 제품명 식별(이름 변형·`product_key`) + 제품 범위 exact 벡터 검색 (`CAST(:q AS vector)`) | `retrieval.py` |
| `contra_tool.py`, `contra_store.py`, `contra_index.py` | 병용금기 도구 `check_contraindication`(정확 조회), 읽기 전용 SQLite 조회, parquet→SQLite 변환 | — |
| `names.py` | 제품명 입력 변형(전각/공백/괄호 제거)과 표시용 줄임(`(수출명:…)` 제거) | — |
| `embedder.py` | 질문 임베딩(Titan V2 · 1024 · normalize), `asyncio.to_thread` | Bedrock 임베딩 호출 |
| `db.py` | 읽기 전용 연결, 연결마다 시크릿 조회, 엔진/Reader | `db.py` |
| `llm_client.py` | Claude 클라이언트(bedrock / mantle) | `llm.py` |
| `prompts.py`, `safety.py` | 시스템 프롬프트·고정 문구, 응급/위기 표현 감지 | `prompt.py` |
| `config.py` | 환경변수 설정(`V2Settings`) | `config.py` |
| `evaluation/` | 평가 케이스 생성, HitRate@k·MRR, **거리 분포·임계값 보정(`retrieval_eval.py`)**, **제품명 변형 평가(`name_eval.py`)**, **모델 비교(`model_compare.py`)** | `evaluation/` |
| `tests/` | 가짜 DB·가짜 Claude 기반 테스트 (DB·AWS 불필요) | — |
| `docker-compose.dev-db.yml` | 로컬 pgvector DB (`pgvector/pgvector:pg17`) | — |

## 합의한 안전장치가 코드 어디에 있나

| 안전장치 | 구현 |
|---|---|
| 읽기 전용 연결 | `db.connect_kwargs`가 연결 시작 파라미터로 `default_transaction_read_only=on`, `statement_timeout`을 건다. 검색 1회는 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY` 트랜잭션(`db.reader_factory_for`). 마스터 계정이어도 쓰기 SQL은 DB가 거부한다. |
| 파라미터 바인딩만 | `Reader.fetch(sql, params)`는 SQL과 값을 분리해 받는다. SQL에 이어 붙는 것은 `search.py`의 고정 조각뿐이고, 제품명·질문·섹션·벡터는 전부 `:name` 파라미터다. 섹션은 허용 목록 검사도 거친다. |
| 비밀값 비노출 | 비밀번호는 `repr`에서 제외. 시크릿/DB/임베딩/도구 오류는 **클래스 이름(+SQLSTATE)만** 로그·응답에 남기고 원인 체인은 끊는다(`from None`). 질문·답변·도구 인자는 로그에 남기지 않는다. |
| 마스터 시크릿 회전 | `RDS_SECRET_ARN`이 있으면 **새 연결을 만들 때마다** Secrets Manager에서 읽는다(`db.open_connection`). 인증 실패(`InvalidPasswordError` 등)면 다시 읽어 한 번 더 시도한다. 풀 연결은 10분 뒤 재생성되고 `pool_pre_ping`을 켠다. |
| 관련 없는 근거 차단 | 거리 임계값(`LLM_V2_MAX_DISTANCE`)을 넘는 문단은 모델에 주지 않는다(`search.retrieve`). 전부 걸러지면 아래 "근거 없음" 규칙이 적용된다. 모델이 고른 정보 유형(`section`)에 문단이 없으면 도구가 같은 임계값으로 모든 유형에 한 번만 넓혀 찾고, 결과에 `[참고]`를 붙여 어느 항목에서 찾았는지 밝히게 한다(`tools.DrugSearchTool.run`). |
| 근거 없으면 모른다 | 검색 근거가 하나도 없으면 모델이 뭐라 답했든 `NO_EVIDENCE_ANSWER`로 대체한다(`agent._assemble`). |
| 허용 도구·한도 | 허용 목록 밖 도구 이름은 실행하지 않고 오류 결과를 돌려준다. 라운드 4·호출 6·60초 기본값(환경변수로 조정). 라운드를 다 쓰면 마지막 호출은 최종 답변을 요구하고, 그래도 도구를 또 부르면 `BUDGET_ANSWER`로 끝낸다. |
| 의료 안전 문구 | 근거 있는 답변 끝에 면책 문구를 코드가 붙인다. 응급 표현이면 119 안내를 앞에 붙이고(모델이 실패해도 나간다), 자해·고의 과다복용 표현이면 약 정보 없이 도움 연결만 한다. |

## 사용법

```python
from app.llm.v2.agent import answer

result = await answer("타이레놀 하루에 몇 번 먹어요?", profile_context="나이: 34, 임신: 아니오")
result.answer      # 사용자에게 보여줄 문장 (근거가 있으면 면책 문구 포함)
result.sources     # ["타이레놀정500밀리그램 · 용법·용량", ...]  실제 검색 결과 기반
result.grounded    # 검색 근거가 있었는가
result.stop_reason # done | no_evidence | needs_clarification | budget | timeout | error | refusal | crisis | empty
result.candidates  # needs_clarification 일 때 [{product_key, product_name, manufacturer}, ...]
```

### 제품명에 괄호가 있을 때 / 제품이 여럿일 때

- 제품명 DB 값은 그대로 두고 **입력 쪽만** 변형해 찾습니다(`names.name_variants`): 원문 → 전각 괄호만 반각 → NFKC → (각각) 공백 제거 → 괄호 내용 제거 순서(NFKC는 `Ⅱ`·`㎎` 같은 글자를 바꾸므로 뒤에 둡니다)이고, 단계는 정확 일치 → 접두 → 포함 순입니다. `lower(product_name)` 인덱스를 그대로 씁니다.
- 괄호 내용을 버려서 찾은 경우는 `approximate`로 표시되고, 도구 결과에 `[참고]`가 붙어 모델이 "어떤 제품 기준인지" 밝히게 합니다.
- 후보가 2~20개면 임의로 고르지 않고 `needs_clarification`(되묻기)입니다. 근거 없이 끝나면 코드가 후보 목록 문구를 만들어 `result.answer`로 줍니다. 21개 이상이면 더 구체적인 이름을 요청합니다.
- `answer()`는 상태를 저장하지 않으므로, 사용자가 후보를 고르면 호출하는 쪽이 `answer(question, product_key=선택한 키)`로 다시 부릅니다. 형식은 `drug:123` / `health_food:…` 이며, 형식이 틀리면 거부합니다.
- 화면에 보이는 제품명은 `(수출명:…)`·`(수출용)` 꼬리표를 떼고 60자로 줄인 `short_name`입니다(DB 값·`product_key`는 그대로).
- 데이터 쪽 정규화(`vector_pipeline`에서 이름 컬럼을 정리해 재임베딩)는 v2 범위 밖이라 하지 않았습니다.

`answer()`는 예외를 밖으로 던지지 않습니다(설정 누락·DB 장애 포함 → `stop_reason="error"`). 기존 `answer_question`과 반환 형태가 달라서
(튜플이 아니라 `AgentAnswer`), 라우터에 연결할 때 `result.answer`를 쓰면 됩니다. 앱 종료 시 `await agent.aclose()`로 DB 엔진을 정리할 수 있습니다.

## 병용금기 확인 (`check_contraindication`)

`data/contraindication/data.parquet`(DUR 병용금기, 80만 행)를 쓰는 별도 도구입니다. 임베딩 검색이 아니라 **정확 조회**입니다: "A랑 B 같이 먹어도 돼요?" → 모델이 제품명 2~5개를 넘기고,
검색 DB에서 제품을 하나씩 확정(`product_key = drug:<item_seq>`)한 뒤, 병용금기 인덱스에서 모든 조합을 조회해 금기 내용·조건·고시일을 **원문 그대로** 돌려줍니다.

- **데이터**: 성분 규칙 1,832행 + 제품 쌍 규칙 약 80만 행. 제품 쌍 행의 `item_seq`(품목기준코드)가 검색 DB의 `product_key`와 같아서 바로 연결됩니다. 변환 때는 제품 쌍 행만 쓰고 양방향 중복을 합칩니다(79만 쌍·규칙 6천 개 → 약 50MB).
- **인덱스 만들기** (한 번만. 런타임은 pyarrow 없이 표준 라이브러리 `sqlite3`로 읽습니다. 변환에만 pyarrow가 필요해 pipeline 가상환경을 씁니다):

```powershell
cd backend
app\llm\v2\dev_data\pipeline-venv\Scripts\python -m app.llm.v2.contra_index --parquet app\llm\v2\data\contraindication\data.parquet --out app\llm\v2\dev_data\contraindication.sqlite
```

- **켜는 방법**: `dev_data/contraindication.sqlite`가 있으면 자동으로 켜지고, 다른 위치는 `LLM_V2_CONTRA_DB`로 지정합니다(지정했는데 파일이 없으면 오류). 파일이 없으면 도구도 시스템 프롬프트의 안내도 빠집니다.
- **안전 규칙(코드)**: 이름이 여러 제품으로 갈리면 임의로 고르지 않고 `[확인 필요]`로 되묻습니다(사용자가 고르면 `products`에 `product_key`를 넣어 다시 호출). 규칙이 없으면 "병용금기 규칙 없음 — 안전하다는 뜻이 아님"으로 전달하고, 근거 목록에는 "병용금기 자료 조회(해당 규칙 없음)"으로만 남깁니다.
  건강기능식품은 이 자료로 확인할 수 없습니다. 조건·비고(예: "48시간 이내", "methotrexate 15mg 이상")는 반드시 함께 전합니다.
- **한계**: 이 자료에 한 번도 등장하지 않는 제품은 "규칙 없음"과 "자료에 없음"을 구분할 수 없어, 결과에 "이 자료에 규칙이 하나도 등록돼 있지 않은 제품"을 표시합니다. 용량·질환 조건별 주의, 효능군 중복 등은 다루지 않습니다.
- **운영 반영 시 결정 필요**: 지금은 로컬 파일입니다. 운영(EC2/RDS)에서는 이 인덱스를 배포물에 포함할지, RDS 테이블로 옮길지(그러면 `vector_pipeline` 쪽 적재가 필요) 팀에서 정해야 합니다.
- **확인**: `uv run python -m app.llm.v2.evaluation.contra_eval --limit 100` — DB에 적재된 의약품 중 실제 병용금기 쌍(양성)과 규칙 없는 쌍(대조군)을 도구로 확인해, 양성은 key로 100% 규칙 있음·대조군은 100% 규칙 없음인지 봅니다(Bedrock 불필요).

## 환경변수

| 이름 | 설명 | 기본값 |
|---|---|---|
| (리전) | **us-east-1 고정**. 임베딩·Claude·Secrets Manager 모두 이 리전을 쓰고, 환경변수로 바꿀 수 없다(`config.REGION`) | us-east-1 |
| `PGHOST`, `PGPORT`, `PGDATABASE` (`DB_HOST` 등도 인식) | DB 위치 | 포트 5432 |
| `RDS_SECRET_ARN` | 있으면 연결마다 여기서 사용자/비밀번호를 읽는다 | — |
| `PGUSER`, `PGPASSWORD` | 시크릿을 쓰지 않을 때(로컬 개발) | — |
| `PGSSLMODE`, `PGSSLROOTCERT` | `verify-full`(기본) / `require` / `disable`, RDS CA 번들 경로 | verify-full |
| `LLM_V2_HAIKU_MODEL_ID`, `LLM_V2_SONNET_MODEL_ID` | 비교·기본 모델. 기본값은 v1 설정과 같은 추론 프로파일 ID이며 v2에서 실제 호출로는 미검증 | `us.anthropic.claude-haiku-5-5`, `us.anthropic.claude-sonnet-5-5` |
| `LLM_V2_DEFAULT_MODEL` | `answer()`가 쓰는 모델 (`haiku` / `sonnet`) | haiku |
| `LLM_V2_MODEL_ID` | 위 둘 대신 쓸 임의 모델 ID (예: `mantle`은 `us.` 없는 ID가 필요할 수 있음) | — |
| `LLM_V2_PROVIDER` | `bedrock`(InvokeModel, EC2 역할로 가능) / `mantle`(IAM에 `bedrock-mantle:CreateInference` 필요) | bedrock |
| `LLM_V2_MAX_TOOL_ROUNDS`, `LLM_V2_MAX_TOOL_CALLS`, `LLM_V2_MAX_SECONDS` | 하니스 한도 | 4 / 6 / 60 |
| `LLM_V2_SEARCH_TOP_K` | 도구 한 번에 가져올 근거 수 | 5 |
| `LLM_V2_CONTRA_DB` | 병용금기 인덱스(SQLite) 경로. 비우면 `dev_data/contraindication.sqlite`가 있을 때만 병용금기 도구를 켬 | (없음) |
| `LLM_V2_MAX_DISTANCE` | 코사인 거리가 이 값보다 큰 근거는 버림(0~2). 전부 버려지면 "근거 없음" 처리. 기본값은 `retrieval_eval --mode calibrate` 결과로 정함(정답 95% 통과·무관 질문 99% 차단). 데이터·임베딩 모델이 바뀌면 다시 보정 | 0.80 |
| `LLM_V2_ALLOW_GLOBAL_SEARCH` | `true`면 제품명 없이 전체 exact 검색 허용(느릴 수 있음) | false |
| `LLM_V2_DB_STATEMENT_TIMEOUT_MS` | 쿼리 최대 시간 | 15000 |

## 로컬 개발 DB (pgvector)

프로젝트 compose의 `postgres:17-alpine`에는 pgvector가 없어서, v2 전용 compose를 따로 둡니다. 아래는 프로젝트 루트 기준 PowerShell 예시이며,
`vector_pipeline`은 **실행만** 하고 산출물(bundle, 임베딩 캐시)은 전부 `v2/dev_data/`(git 제외)에 둡니다.

```powershell
# 0) 로컬 전용 비밀번호는 환경변수로만 (파일에 적지 않는다)
$env:LLM_V2_DEV_DB_PASSWORD = "로컬에서만 쓸 임의 값"
docker compose -f backend/app/llm/v2/docker-compose.dev-db.yml up -d

# 1) 파이프라인 실행 환경 (vector_pipeline 폴더에 .venv/__pycache__ 를 만들지 않도록)
cd backend\app\llm\v2
python -m venv dev_data\pipeline-venv
dev_data\pipeline-venv\Scripts\python -m pip install -r ..\..\..\..\vector_pipeline\requirements.txt
$env:PYTHONDONTWRITEBYTECODE = "1"
$pipe = "..\..\..\..\vector_pipeline\run.py"
$py   = "dev_data\pipeline-venv\Scripts\python"

# 2) 샘플 bundle 생성 (--limit 으로 소량) — AWS/DB 호출 없음. 경로는 실제 값으로 바꾸세요(꺾쇠 <> 는 PowerShell에서 오류)
& $py $pipe prepare --drug "C:\경로\drug\data.parquet" --health-food "C:\경로\health_food\data.parquet" --output dev_data\bundle --limit 200
& $py $pipe validate --input dev_data\bundle

# 3) 임베딩 (Bedrock 호출 · AWS 자격증명 필요). 캐시 경로를 반드시 v2 안으로 지정!
$env:BEDROCK_REGION = "us-east-1"; $env:AWS_REGION = "us-east-1"
& $py $pipe embed --input dev_data\bundle --cache dev_data\embedding-cache.sqlite

# 4) 로컬 DB에 적재 (SSL 끔: 로컬 컨테이너)
$env:PGHOST="localhost"; $env:PGPORT="5433"; $env:PGDATABASE="pill"; $env:PGUSER="pill_dev"
$env:PGPASSWORD=$env:LLM_V2_DEV_DB_PASSWORD; $env:PGSSLMODE="disable"
& $py $pipe init-db
& $py $pipe ingest --input dev_data\bundle --cache dev_data\embedding-cache.sqlite
```

샘플 bundle은 `--publish`가 거부됩니다(전체 스냅샷이 아니므로). 검색은 활성 스냅샷이 있어야 하므로, **로컬 개발 DB에서만** 아래로 직접 활성화합니다.
운영(RDS)에서는 쓰지 마세요.

```powershell
docker compose -f docker-compose.dev-db.yml exec -T pgvector psql -U pill_dev -d pill -c "INSERT INTO product_search.active_snapshot(singleton, run_id) SELECT true, run_id FROM product_search.ingestion_runs WHERE status='complete' ORDER BY updated_at DESC LIMIT 1 ON CONFLICT (singleton) DO UPDATE SET run_id = EXCLUDED.run_id;"
```

HNSW 인덱스(`create-index`)는 이 exact 검색에서 쓰이지 않으므로 로컬에서는 생략해도 됩니다.

## 평가 (HitRate@k, MRR)

```powershell
cd backend
uv run python -m app.llm.v2.evaluation.build_cases --bundle app\llm\v2\dev_data\bundle --max-cases 60
uv run python -m app.llm.v2.evaluation.retrieval_eval --k 5                # 제품 범위 검색: 올바른 섹션이 위에 오는가 (결과에 코사인 거리 표시)
uv run python -m app.llm.v2.evaluation.retrieval_eval --k 5 --mode global  # 제품명 없이 전체 검색(느림)
uv run python -m app.llm.v2.evaluation.retrieval_eval --mode offtopic      # 약과 무관한 질문의 1등 거리 분포
uv run python -m app.llm.v2.evaluation.retrieval_eval --mode calibrate --quiet   # 정답 거리 + 무관 거리 → 임계값 후보 표
uv run python -m app.llm.v2.evaluation.name_eval --bundle app/llm/v2/dev_data/bundle --limit 300   # 제품명 변형 평가
```

질문 문장은 섹션별 템플릿이 만든 **초안**입니다. 적재된 제품만 쓰고 같은 seed면 같은 케이스가 나옵니다.
평가는 임계값을 적용하지 않고 각 결과의 거리를 출력합니다. 정답 근거와 무관한 근거의 거리가 갈리는 지점을 보고 `LLM_V2_MAX_DISTANCE`를 정하세요
(너무 낮으면 정답도 걸러져 "확인할 수 없어요"가 늘고, 너무 높으면 무관한 문단이 모델에 들어갑니다).
도구가 제품명을 올바르게 뽑는지(에이전트 단위 평가)는 아직 평가에 포함하지 않았습니다.

### 임계값 보정 (`--mode offtopic` / `--mode calibrate`)

- `scoped`와 `calibrate`는 **정답 근거의 코사인 거리**를 최소·중앙값·90%·최대로 요약해 보여 줍니다(못 찾은 케이스는 "못 찾음"으로 따로 셉니다).
- `offtopic`은 약과 무관한 질문(날씨, 코딩, 보험 등 `evaluation/dataset.py`의 `OFFTOPIC_QUESTIONS`)을 각 케이스의 제품 범위에서 검색해 **1등 거리**의 분포를 보여 줍니다.
  제품 수는 `--offtopic-limit`(기본 20), 질문은 `--offtopic-file`(한 줄에 하나)로 바꿀 수 있습니다. 약 관련이지만 그 제품에 없는 내용(애매한 질문)을 섞어 넣으면 더 현실적입니다.
- `calibrate`는 둘을 합쳐 임계값 후보별 "정답 통과율 / 무관 차단율" 표와, 둘의 합이 가장 큰 후보를 보여 줍니다. 두 분포가 겹치면 경고가 나옵니다(임계값 하나로 완전히 나눌 수 없다는 뜻).
  표는 참고용이고, 값은 두 위험 중 무엇을 더 줄일지 정해서 `$env:LLM_V2_MAX_DISTANCE`로 시험한 뒤 정합니다.
- 무관 질문 평가에는 Bedrock 임베딩이 질문 수만큼(같은 문장은 한 번만) 쓰입니다.

### 제품명 변형 평가 (`name_eval`)

DB의 제품명을 사용자가 말할 법한 형태로 바꿔(괄호 제거, 전각 괄호, 공백 삽입, 앞 절반만, 괄호 안을 다른 내용으로) 넣고, 결과를 분류합니다.
`exact_hit`/`approx_hit`(한 번에 확정), `clarify_incl`(되묻기 후보에 정답 포함), `clarify_excl`, `wrong_product`(다른 제품으로 확정 — 가장 위험), `too_many`, `not_found`.
Bedrock을 쓰지 않고(고정 벡터) 읽기 전용 DB 연결만 필요합니다. `--bundle`을 주면 bundle의 제품 전체(상한 `--limit`)로, 아니면 `cases.jsonl`의 제품으로 돌립니다.
`wrong_product`가 0에 가까워야 안전하고, 되묻기는 정상 동작입니다.

## 모델 비교 (Haiku vs Sonnet)

같은 질문·DB·도구·프롬프트·한도에서 **모델 ID만 바꿔** 돌리고 지표를 나란히 보여 줍니다. 모델 ID는 코드에 박지 않았습니다.
`--model`을 생략하면 위 환경변수의 haiku/sonnet 기본 ID(v1 설정과 동일)로 비교합니다. 다른 모델을 넣으려면 `--model 라벨=모델ID`를 2개 이상 지정하세요. `LLM_V2_PROVIDER`는 두 모델에 똑같이 적용됩니다.

```powershell
cd backend
uv run python -m app.llm.v2.evaluation.model_compare --limit 30
```

- 질문은 `evaluation/generated/cases.jsonl`(기본) 또는 `--questions 파일.jsonl`의 `question` 필드. 실제 사용자 질문처럼 제품명이 없거나 애매한 문장을 섞은 JSONL을 따로 만들면 모델 차이가 더 잘 드러납니다.
- 자동 지표: 근거 기반 답변 비율, 근거 없음/실패 비율, 평균·p90 소요 시간, 도구 호출·라운드 수, 입력/출력 토큰, 기대 제품·섹션의 근거를 찾아왔는지.
  토큰은 가격 계산용이 아니라 상대 비교용입니다(요금은 직접 곱하세요).
- 답변 문장의 품질(정확성, 말투, 쉬운 설명)은 자동 판정하지 않습니다. 실행 후 저장되는 `evaluation/generated/model_compare-*.jsonl`에 질문별 두 모델의 답변 전문이 들어 있으니 사람이 읽고 비교하세요(건강 관련 답변이 담겨 git에서 제외됩니다).
- 저장 파일의 `tool_trace`에 모델이 도구에 넘긴 인자(제품명·섹션·`product_key`·질문)와 결과 첫머리가 들어 있어, 모델이 갈린 질문의 원인(제품명을 잘못 넘겼는지 등)을 볼 수 있습니다. 로그에는 남기지 않고 이 로컬 파일에만 저장됩니다.
- 모델을 한 개만 바꿔 쓰려면 `LLM_V2_MODEL_ID`만 바꾸면 됩니다.

## 테스트

```powershell
cd backend
uv run pytest app/llm/v2/tests
```

`pyproject.toml`의 `testpaths`가 `tests`뿐이라 경로를 직접 지정해야 합니다. DB·AWS·Claude 없이 가짜 객체로 돌아갑니다.

## 확인된 것 / 확인되지 않은 것

확인됨(작성 환경에서 실행):
- 위 테스트 139개가 통과했다(변이 확인: 근거 검사·허용 도구 검사를 지우면 해당 테스트가 실패한다).
- 검색 SQL을 실제 PostgreSQL 16에서 `vector_pipeline/sql/init.sql` 스키마로 실행했다: 이름 단계(exact/prefix/contains), `%`·`_` 이스케이프, 악의적 입력 무해, 제품 범위 한정, 공유 본문의 `source_count`, 읽기 전용 트랜잭션의 쓰기 거부, 괄호 이름 처리(괄호 포함/제외 입력, 전각 괄호, 공백, 근사 일치, 후보 여럿 → 되묻기, `product_key` 지정). 제품명 변형 평가(`name_eval`)의 집계 로직도 같은 DB로 시험했다(3개 제품, 변형 6종). 병용금기 도구는 실제 `data.parquet`에서 만든 인덱스로, 같은 PostgreSQL에 적재한 실제 제품명·`item_seq`와 함께 시험했다(실제 규칙 쌍 9개 모두 확인, 규칙 없는 대조군 2쌍은 규칙 없음, 이름이 갈리는 입력은 되묻기). 단, **pgvector는 없어서** `vector` 타입과 `<=>`는 같은 모양의 대체물로 시험했다.

확인 안 됨(첫 실제 실행에서 확인 필요):
1. 진짜 pgvector에서 `CAST(:q AS vector)` 문자열 바인딩(asyncpg가 `vector` 파라미터를 텍스트로 보내는지)과 SQLAlchemy `async_creator` 경로. 로컬 compose DB에서 가장 먼저 확인하세요.
2. Bedrock 엔드포인트(InvokeModel / Mantle)의 **도구 호출 지원**과 모델 ID(기본값은 v1에서 가져온 `us.anthropic.claude-*-5-5`). EC2 역할에는 `bedrock:InvokeModel`만 있어 `bedrock`이 기본이며, `mantle`은 IAM 추가가 필요하다.
3. 한국어 질문의 실제 검색 품질(평가 스크립트로 측정), pg_trgm의 한글 동작(DB 로케일 의존), 전체(제품명 없는) 검색의 지연시간.
4. 응급·위기 감지는 정규식 기반 보조 장치라 놓치는 표현이 있을 수 있다. 상담전화 번호(109)는 배포 전에 최신 여부를 확인하세요.

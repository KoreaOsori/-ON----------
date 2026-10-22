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
| `api.py` | HTTP API(FastAPI): `POST /llm/v2/ask`, `GET /llm/v2/models`, `GET /llm/v2/health`. API 키 인증·동시 요청 제한 | — |
| `harness.py` | `Limits`(라운드/호출/시간), `Budget`, `ALLOWED_TOOLS` | `harness.py` |
| `tools.py` | `search_drug_info` 도구 정의·실행·`[출처 \| 제품명 \| 섹션]` 포매터 | `tools/rag_tools.py` |
| `search.py` | 제품명 식별(이름 변형·`product_key`) + 제품 범위 exact 벡터 검색 (`CAST(:q AS vector)`) | `retrieval.py` |
| `contra_tool.py`, `contra_rds.py`, `contra_store.py`, `contra_index.py` | 병용금기 도구 `check_contraindication`(정확 조회), RDS(`gold.drug_contraindication`) 조회, 읽기 전용 SQLite 조회, parquet→SQLite 변환 | — |
| `names.py` | 제품명 입력 변형(전각/공백/괄호 제거)과 표시용 줄임(`(수출명:…)` 제거) | — |
| `embedder.py` | 질문 임베딩(Titan V2 · 1024 · normalize), `asyncio.to_thread` | Bedrock 임베딩 호출 |
| `db.py` | 읽기 전용 연결, 연결마다 시크릿 조회, 엔진/Reader | `db.py` |
| `aws_auth.py` | AWS 자격증명 정책: EC2에서는 인스턴스 역할만 허용, 로컬은 기본 체인 (`LLM_V2_AUTH_MODE`) | — |
| `llm_client.py` | Claude 클라이언트(bedrock / mantle) | `llm.py` |
| `prompts.py`, `safety.py` | 시스템 프롬프트·고정 문구, 응급/위기 표현 감지 | `prompt.py` |
| `config.py` | 환경변수 설정(`V2Settings`) | `config.py` |
| `evaluation/` | 평가 케이스 생성, HitRate@k·MRR, **거리 분포·임계값 보정(`retrieval_eval.py`)**, **제품명 변형 평가(`name_eval.py`)**, **모델 비교(`model_compare.py`)**, **시나리오 점검(`scenario_check.py`, 질문 세트 `scenarios.jsonl`)**, **대상 DB 점검(`db_probe.py`)** | `evaluation/` |
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
| 근거 없으면 모른다 | 검색 근거가 하나도 없으면 모델이 뭐라 답했든 고정 문구로 대체한다(`agent._assemble`). 도구로 찾아봤지만 없으면 `NO_EVIDENCE_ANSWER`("등록된 정보에서 확인할 수 없어요…"), 도구를 한 번도 못 쓴 경우(약 이름이 없거나 증상별 약 추천·성분으로 약 찾기 같은 범위 밖 질문)는 `OUT_OF_SCOPE_ANSWER`로 "약 이름을 알려주시면 약 정보와 병용 주의사항을 안내해 드려요"를 알린다. 둘 다 `status`는 `no_evidence`다. |
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

- **자료 출처** (`LLM_V2_CONTRA_SOURCE`, 기본 `auto`): ① `LLM_V2_CONTRA_DB`를 지정했으면 그 SQLite(파일이 없으면 오류) ② `dev_data/contraindication.sqlite`가 있으면 그 파일 ③ 둘 다 없으면 **RDS의 `gold.drug_contraindication`**을 읽습니다(EC2는 파일이 없으므로 환경변수 없이 이쪽). 값을 `rds`/`sqlite`로 고정하거나 `off`로 끌 수 있습니다(`off`면 도구도 시스템 프롬프트의 안내도 빠짐). 로컬 개발 DB에 `gold` 스키마가 없으면 `off`로 두세요(켜 두면 병용금기 질문에 "조회할 수 없다"는 안내가 나갑니다).
- **RDS 읽기** (`contra_rds.py`): 검색과 같은 읽기 전용 트랜잭션에서 SELECT만 하고 값은 모두 바인딩합니다. 테이블에는 `품목 DUR`(약 79.5만 행, SQLite 쌍 수와 거의 같음)과 `성분 규칙`(약 31.5만 행, 성분 단위 규칙이 제품 쌍으로 풀린 것)이 함께 있고, 한 쌍이 양방향으로 저장돼 있어 `item_seq=앞 제품 AND mixture_item_seq=뒤 제품`으로 조회합니다(한쪽만 있는 쌍을 위해 비면 반대 방향도 조회). 결과에 `규칙 종류`(품목 DUR / 성분 규칙)가 붙고, 품목 DUR이 먼저 나옵니다. 판정은 데이터 담당 쪽 기준을 따릅니다: **품목 DUR이 하나라도 있으면 '병용금기'**(식약처가 제품에 적용), **성분 규칙만 있으면 '성분 기준 주의'**(헤더·출처 라벨·모델 지시가 달라지고 '병용금기'라고 단정하지 않음). 이 테이블에는 적재 기준일이 없어 "자료 기준일"은 표시하지 않습니다. `gold` 스키마는 데이터 파이프라인 소유라 읽기만 하며, 느리면 `(item_seq, mixture_item_seq)` 인덱스를 그쪽에 요청합니다.
- **성분 이름도 받습니다 (RDS 저장소일 때)**: 제품명으로 아무것도 찾지 못한 이름은 `gold.drug_ingredient`에서 성분 이름으로 한 번 더 찾아 DUR 성분 코드(D코드)로 바꿉니다("아세트아미노펜 × 와파린정" 같은 입력). 제품 × 제품은 지금처럼 `item_seq` 쌍으로, 성분이 하나라도 낀 조합은 `drug_contraindication`의 `ingr_code`/`mixture_ingr_code`로 조회합니다(제품 쪽 코드는 `drug_ingredient`에서 가져옴). 제품명이 여럿에 걸리면(되묻기) 성분으로 넘어가지 않습니다 — 제품이 먼저입니다. 성분 단위라 **제형 같은 제품별 조건은 반영되지 않고 복합제 규칙은 정확히 맞지 않을 수 있어**, 결과에 `[성분 기준 조회]` 안내를 코드가 붙이고 모델이 답변에서 밝히게 합니다. 이름은 있으나 D코드가 없는 성분, 성분 코드를 찾지 못한 제품은 "규칙 없음"이 아니라 `[확인 불가]`로 알립니다. 판정 기준(품목 DUR이 있으면 금기, 성분 규칙만이면 성분 기준 주의)은 제품 조회와 같습니다. "이 성분이 든 약 목록" 찾기는 하지 않습니다. 조회 SQL은 임시 PostgreSQL 16에서 문법과 결과를 확인했지만 RDS에서 돌려 본 것은 아닙니다. `(ingr_code, mixture_ingr_code)` 인덱스는 `pipeline/gold/schema.sql`에 추가됐고 다음 적재부터 생깁니다(그 전에는 전체 스캔이라 느릴 수 있음). SQLite 저장소는 성분 조회를 지원하지 않습니다.
- **안전 규칙(코드)**: 이름이 여러 제품으로 갈리면 임의로 고르지 않고 `[확인 필요]`로 되묻습니다(사용자가 고르면 `products`에 `product_key`를 넣어 다시 호출). 규칙이 없으면 "병용금기 규칙 없음 — 안전하다는 뜻이 아님"으로 전달하고, 근거 목록에는 "병용금기 자료 조회(해당 규칙 없음)"으로만 남깁니다.
  조건·비고(예: "48시간 이내", "methotrexate 15mg 이상")는 반드시 함께 전합니다.
- **건강기능식품이 섞인 조합**: 병용금기(DUR) 자료는 의약품 전용이라 판정하지 않습니다(v1과 같은 정책). 대신 건강기능식품의 **섭취 주의사항(`precautions`)을 문단 단위로 전부** 돌려주고(임베딩 순위 없이 `fetch_section_texts`로 읽음), 모델에게는 "적힌 내용만 전하고 상호작용을 추정하거나 안전하다고 말하지 말 것"을 도구 결과와 프롬프트로 지시합니다. 의약품이 둘 이상이면 의약품끼리는 평소처럼 병용금기를 조회합니다. 글자 예산은 전체 6,000자(제품 수로 나눔, 제품당 최소 1,500자)이며 **문단 중간에서 자르지 않고**, 첫 문단은 항상 담습니다. 예산을 넘겨 못 담은 문단이 있으면 결과에 "일부 문단을 생략했습니다"를 적어 모델이 그 사실을 밝히게 합니다. 등록된 주의사항이 없는 제품은 "[확인 불가]"로 알립니다.
- **한계**: 이 자료에 한 번도 등장하지 않는 제품은 "규칙 없음"과 "자료에 없음"을 구분할 수 없어, 결과에 "이 자료에 규칙이 하나도 등록돼 있지 않은 제품"을 표시합니다. 용량·질환 조건별 주의, 효능군 중복 등은 다루지 않습니다.
- **운영(EC2/RDS)**: 파일을 배포하지 않고 RDS 테이블을 읽습니다(월 1회 데이터 파이프라인 적재로 갱신). SQLite 인덱스는 로컬 개발·평가(`contra_eval`)용으로 남아 있으며, RDS 쪽은 `성분 규칙`이 더해져 범위가 더 넓습니다.
- **확인**: `uv run python -m app.llm.v2.evaluation.contra_eval --limit 100` — DB에 적재된 의약품 중 실제 병용금기 쌍(양성)과 규칙 없는 쌍(대조군)을 도구로 확인해, 양성은 key로 100% 규칙 있음·대조군은 100% 규칙 없음인지 봅니다(Bedrock 불필요).

## HTTP API (FastAPI)

에이전트를 서비스로 띄웁니다. 기존 `main.py`는 건드리지 않았고, 독립 앱으로 실행합니다(v1은 8011, v2는 8012).

```powershell
cd backend
uv run python -m uvicorn app.llm.v2.api:app --host 127.0.0.1 --port 8012
```

Swagger는 http://127.0.0.1:8012/docs 입니다. 앱이 시작될 때 환경변수로 설정을 읽고 에이전트를 만듭니다(설정 오류나, `LLM_V2_CONTRA_DB`를 지정했는데 파일이 없으면 시작이 실패합니다).

| 엔드포인트 | 설명 |
|---|---|
| `POST /llm/v2/ask` | 질문 → 답변. 아래 요청·응답 참고 |
| `GET /llm/v2/models` | 사용 모델·켜진 도구·거리 기준 확인(인증 필요) |
| `GET /llm/v2/health` | 프로세스 생존 확인(인증 없음, DB·Bedrock은 확인하지 않음) |

요청(`question`만 필수):

```json
{
  "question": "라식스주사랑 알보젠겐타마이신황산염주 같이 써도 돼요?",
  "product_key": "drug:195700010",
  "profile_context": "30대 임산부"
}
```

- `product_key`는 `status`가 `needs_clarification`일 때 사용자가 고른 후보의 값입니다. 서버는 대화 상태를 저장하지 않으므로 같은 질문에 이 값을 붙여 다시 보냅니다.
- `profile_context`는 모델에 **데이터로만** 전달됩니다(1000자 이하). 질문이 500자(설정값 `max_question_chars`)를 넘으면 422입니다.

응답:

```json
{
  "status": "done",
  "answer": "...(면책 문구 포함)",
  "grounded": true,
  "emergency": false,
  "sources": ["알보젠겐타마이신황산염주 × 라식스주사(푸로세미드) · 병용금기(DUR)"],
  "candidates": [],
  "tools_used": ["check_contraindication"],
  "rounds": 2,
  "usage": {"input_tokens": 5200, "output_tokens": 420},
  "latency_ms": 5300,
  "model_id": "us.anthropic.claude-haiku-5-5"
}
```

| `status` | HTTP | 의미 |
|---|---|---|
| `done` | 200 | 근거가 있는 답변 |
| `no_evidence` | 200 | 근거 없음(고정 안내, 모델 문장 폐기) |
| `needs_clarification` | 200 | 제품 후보가 여럿. `candidates`(`product_key`, `product_name`, `manufacturer`)를 보여 주고 다시 질문 |
| `crisis` / `refusal` / `budget` / `empty` | 200 | 위기 안내 / 모델 거절 / 한도 초과 / 빈 질문(고정 안내) |
| (오류) | 503 | 모델·DB 오류, 또는 동시 요청이 많아 대기 시간 초과(`Retry-After` 헤더) |
| (시간 초과) | 504 | 전체 시간(`LLM_V2_MAX_SECONDS`) 초과 |
| (검증 실패) | 422 | 빈 질문, 너무 긴 질문, 잘못된 `product_key`, 알 수 없는 필드 |
| (인증 실패) | 401 | `LLM_V2_API_KEY`가 설정됐는데 `X-API-Key`가 없거나 다름 |

보안·운영:
- `LLM_V2_API_KEY`를 설정하면 `X-API-Key`가 일치해야 합니다(상수 시간 비교, ASCII 문자열 권장). 설정하지 않으면 인증 없이 열리므로 **localhost로만** 띄우고(시작 때 경고 로그), 외부에 열 때는 키와 HTTPS 프록시·보안그룹으로 접근을 제한하세요. 이 키는 AWS 키와 무관합니다.
- 오류 응답에는 내부 메시지를 담지 않고, 로그에는 질문·프로필·비밀값을 남기지 않습니다.
- 동시에 처리하는 질문은 `LLM_V2_API_MAX_CONCURRENCY`(기본 4)개입니다. 나머지는 `LLM_V2_API_QUEUE_SECONDS`(기본 5초)까지 기다리고, 넘으면 503입니다(DB 연결 풀과 Bedrock 호출 보호).
- EC2에서는 **환경변수 없이** v1과 같은 RDS 설정(호스트·DB·시크릿·CA)으로 연결하고, 인스턴스 역할 자격증명이 아니면 시작을 막습니다(아래 "AWS 자격증명과 DB 연결"). 병용금기는 파일 없이 RDS(`gold.drug_contraindication`)를 읽으므로 DB 계정에 그 테이블의 SELECT 권한이 있어야 합니다(현재 마스터 계정으로 확인함). Bedrock·Secrets Manager 권한은 따로 필요합니다. v1의 `iam/` 정책 템플릿을 참고하세요.
- 백엔드는 이 서버를 HTTP로 호출하거나(권장), `from app.llm.v2.agent import answer`로 직접 호출합니다. 라우터만 다른 앱에 붙이면 시작 때 설정되는 `app.state`가 없어 동작하지 않습니다.

### 공개 주소에 붙이기 (`/api/llm/v2`)

v1과 같은 방식으로 백엔드 앱(`backend/app/main.py`)에 v2를 mount 합니다. 기존 Nginx `/api/` 프록시를 그대로 쓰므로 별도 컨테이너·nginx 변경이 필요 없습니다.

- Swagger: `http://<EC2 주소>/api/llm/v2/docs` (부모 앱 문서가 꺼져 있어도 열림), OpenAPI: `/api/llm/v2/openapi.json`
- 질문: `POST /api/llm/v2/ask`, 모델·도구 확인: `GET /api/llm/v2/models`, 생존 확인: `GET /api/llm/v2/health`
- **`LLM_V2_API_KEY`가 필수입니다.** 공개 경로에서 키 없이 열리면 누구나 Bedrock 비용을 쓰게 되므로, 키가 없으면 v2 경로는 503을 돌려주고 로그에 이유를 남깁니다(백엔드는 정상 실행). Swagger의 Authorize에 같은 키를 넣으세요.
- **v2 초기화가 실패해도 백엔드는 계속 뜹니다.** 자격증명 정책(EC2 역할 아님)·설정 오류 등으로 v2가 시작하지 못하면 v2 경로만 503입니다. 웹 서비스를 v2 때문에 내리지 않기 위한 장치입니다. 로그에 `LLM v2 시작 실패`가 남습니다.
- 환경변수는 `deploy/ec2/.env`(git 제외, 백엔드 컨테이너가 선택적으로 읽음)에 둡니다. compose 수정은 필요 없습니다.

```
LLM_V2_API_KEY=<임의의 긴 값>
LLM_V2_AUTH_MODE=ec2_role
```

- 같은 프로세스에 올라가므로 메모리가 v2만큼(대략 200~400MB, 실측 아님) 늘어납니다.
- 반영: PR 머지 후 EC2에서 `git pull`, `deploy/ec2`에서 `docker compose up -d --build backend`.
- 기존 독립 실행(`app.llm.v2.api:app`, `/llm/v2/*`)과 `llm-v2` 컨테이너는 그대로 동작합니다.
- 이 경로가 동작하려면 RDS에 `product_search`(벡터 DB)가 적재되어 있어야 합니다. 없으면 `/ask`는 오류로 끝납니다.

## AWS 자격증명과 DB 연결

**자격증명(`LLM_V2_AUTH_MODE`)** — v1(`aws_auth.py`)과 같은 검사입니다. 정적 키나 공유 프로필이 먼저 잡혀 운영 서버가 역할이 아닌 자격증명으로 Bedrock·Secrets Manager를 호출하는 일을 막습니다.

| 값 | 동작 |
|---|---|
| `auto` (기본) | EC2 위에서 실행 중이면 엄격, 아니면 완화. 로컬 개발은 설정 없이 그대로 동작 |
| `ec2_role` | 항상 엄격: 자격증명이 EC2 인스턴스 역할(`iam-role`)이 아니면 시작 실패 |
| `default_chain` | 항상 완화: boto3 기본 자격증명 체인(로컬 프로필·SSO 등) |

- EC2 감지는 리눅스 DMI 정보(`Amazon EC2`)로 하며 네트워크 호출은 없습니다. 감지에 실패하면 완화로 동작하므로(fail-open) **운영 서버에는 `LLM_V2_AUTH_MODE=ec2_role`을 명시**하는 편이 안전합니다(특히 컨테이너).
- 엄격 모드에서는 서버 환경에 `AWS_ACCESS_KEY_ID`, `AWS_PROFILE`, `AWS_BEARER_TOKEN_BEDROCK` 등을 넣지 마세요. IMDS는 켜 두고, EC2 안의 Docker라면 컨테이너가 IMDS에 닿도록 hop limit을 2 이상으로 설정해야 합니다.
- 검사는 `build_agent`(= HTTP API 시작, `answer()` 첫 호출)에서만 합니다. 평가 스크립트(`retrieval_eval` 등)는 영향받지 않습니다.
- 오류 메시지에는 자격증명 값이 아니라 방식 이름(`env`, `iam-role` 등)만 나옵니다.

**DB 연결** — `PGHOST`(또는 `DB_HOST`)가 **없으면** v1(`database.py`)과 같은 고정 RDS 설정을 씁니다: 호스트 `pill-check-dev-postgres…rds.amazonaws.com`, DB `pill`, 포트 5432, Secrets Manager 시크릿 `rds!db-71cf9992-…`(연결마다 새로 읽음), TLS `verify-full` + v2 폴더의 RDS CA 번들(`v2/certs/us-east-1-bundle.pem`, v1의 같은 파일을 복사해 둔 것이라 v1과 독립적). 그래서 EC2에서는 DB 환경변수가 필요 없습니다.

- `PGHOST`가 **있으면** 고정 설정을 쓰지 않고 환경변수만 씁니다(아래 "로컬 개발 DB"의 평가용 로컬 DB). 일부만 주면 나머지는 비어 오류로 드러납니다.
- 고정 설정 위에서도 `PGDATABASE`, `RDS_SECRET_ARN`, `PGSSLROOTCERT`, `PGSSLMODE`로 항목별로 바꿀 수 있습니다.
- `PGHOST`를 RDS 호스트(`*.rds.amazonaws.com`)로 직접 주고 `PGSSLROOTCERT`를 생략하면 같은 CA 번들을 씁니다. 그 밖의 호스트에는 적용하지 않습니다.
- 주의: 로컬에서 `PGHOST`를 설정하지 않고 실행하면 위 고정 RDS에 연결을 시도합니다(VPC 밖이면 실패, 읽기 전용 연결).
- `v2/certs/us-east-1-bundle.pem`은 AWS 공식 RDS CA 번들(공개 신뢰 앵커 3개, 개인 키 아님)이며 `certs/.gitignore`로 git에 포함됩니다. CA가 바뀌면 [공식 번들](https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem)로 갱신하세요.

## 환경변수

| 이름 | 설명 | 기본값 |
|---|---|---|
| (리전) | **us-east-1 고정**. 임베딩·Claude·Secrets Manager 모두 이 리전을 쓰고, 환경변수로 바꿀 수 없다(`config.REGION`) | us-east-1 |
| `PGHOST`, `PGPORT`, `PGDATABASE` (`DB_HOST` 등도 인식) | DB 위치. **`PGHOST`를 주면 v1 고정 RDS 설정 대신 환경변수만 사용** | v1 고정 RDS / 5432 / `pill` |
| `RDS_SECRET_ARN` | 연결마다 여기서 사용자/비밀번호를 읽는다(시크릿 이름도 가능) | v1 고정 시크릿(`PGHOST`가 없을 때) |
| `PGUSER`, `PGPASSWORD` | 시크릿을 쓰지 않을 때(로컬 개발) | — |
| `PGSSLMODE`, `PGSSLROOTCERT` | `verify-full`(기본) / `require` / `disable`, RDS CA 번들 경로 | verify-full / `v2/certs` CA 번들(RDS 호스트일 때) |
| `LLM_V2_AUTH_MODE` | AWS 자격증명 정책 `auto` / `ec2_role` / `default_chain` (위 "AWS 자격증명과 DB 연결") | auto |
| `LLM_V2_HAIKU_MODEL_ID`, `LLM_V2_SONNET_MODEL_ID` | 비교·기본 모델. 기본값은 v1 설정과 같은 추론 프로파일 ID이며 v2에서 실제 호출로는 미검증 | `us.anthropic.claude-haiku-5-5`, `us.anthropic.claude-sonnet-5-5` |
| `LLM_V2_DEFAULT_MODEL` | `answer()`가 쓰는 모델 (`haiku` / `sonnet`) | haiku |
| `LLM_V2_MODEL_ID` | 위 둘 대신 쓸 임의 모델 ID (예: `mantle`은 `us.` 없는 ID가 필요할 수 있음) | — |
| `LLM_V2_PROVIDER` | `bedrock`(InvokeModel, EC2 역할로 가능) / `mantle`(IAM에 `bedrock-mantle:CreateInference` 필요) | bedrock |
| `LLM_V2_MAX_TOOL_ROUNDS`, `LLM_V2_MAX_TOOL_CALLS`, `LLM_V2_MAX_SECONDS` | 하니스 한도 | 4 / 6 / 60 |
| `LLM_V2_SEARCH_TOP_K` | 도구 한 번에 가져올 근거 수 | 5 |
| `LLM_V2_CONTRA_DB` | 병용금기 인덱스(SQLite) 경로. 비우면 `dev_data/contraindication.sqlite`가 있을 때 그 파일을 쓰고, 없으면 RDS를 읽음 | (없음) |
| `LLM_V2_CONTRA_SOURCE` | 병용금기 자료 출처: `auto` / `rds` / `sqlite` / `off` | `auto` |
| `LLM_V2_API_KEY` | HTTP API의 `X-API-Key` 값. 비우면 인증 없이 열림(localhost 전용) | (없음) |
| `LLM_V2_API_MAX_CONCURRENCY`, `LLM_V2_API_QUEUE_SECONDS` | HTTP API 동시 처리 질문 수 / 자리가 날 때까지 기다리는 시간(초) | 4 / 5 |
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

## 시나리오 점검 (프롬프트를 고치며 반복 확인)

`evaluation/scenarios.jsonl`의 질문 17개(약 정보·병용·건강기능식품·응급/위기·범위 밖·프롬프트 주입·용량 변경 등)를 실제 에이전트로 돌려 **기대한 동작**이 나오는지 표로 봅니다.
자동 판정은 동작만 봅니다: 종료 상태, 쓴 도구, 출처, 근거 기반 답변의 고정 꼬리말, 있으면 안 되는 표현, "안전/괜찮다/문제없다"를 유보 없이 말하는 문장(WARN, 휴리스틱). **답변 문장이 자연스럽고 정확한지는 채점하지 않습니다.** `--show`나 저장된 JSONL을 사람이 읽고 판단하세요.

```powershell
cd backend
uv run python -m app.llm.v2.evaluation.scenario_check                  # 전체
uv run python -m app.llm.v2.evaluation.scenario_check --only S05,S07 --show
uv run python -m app.llm.v2.evaluation.scenario_check --model sonnet   # 모델을 바꿔 비교
```

- 제품명은 로컬 개발 DB에 있던 제품입니다. 대상 DB에 없으면 `no_evidence`가 나올 수 있으니 `scenarios.jsonl`의 이름을 그 DB에 있는 제품으로 바꿔 쓰세요.
- 답변 전문은 `evaluation/generated/scenario_check-<시각>.jsonl`에만 저장됩니다(git 제외). 프롬프트를 고치기 전후 파일을 나란히 비교하세요.
- FAIL이 하나라도 있으면 종료 코드 1입니다.
- 모든 시나리오가 `no_evidence`로 끝나고 로그에 `ProgrammingError`가 나오면 대상 DB의 스키마가 v2의 기대와 다른 것입니다. `uv run python -m app.llm.v2.evaluation.db_probe`가 어느 테이블·컬럼이 없는지 DB 오류 메시지와 함께 보여 줍니다(읽기 전용, 제품 본문·비밀번호는 출력하지 않음).

### 실제 RDS에 로컬에서 붙어 반복하기 (SSM 터널)

팀 규칙상 EC2에서 코드를 직접 고치지 않으므로, 프롬프트를 다듬는 반복은 내 PC에서 실제 RDS(`product_search`)에 붙어서 하고, 마지막에 PR → master → EC2 pull·재빌드 후 같은 점검을 한 번 더 합니다.

1. 터미널 하나에서 터널을 열어 둡니다(팀 문서 5-1. 내 PC의 5432가 쓰이고 있으면 `localPortNumber=15432`).

```powershell
aws ssm start-session --target i-00d9e7255e6bcc7c6 --region us-east-1 --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters host=pill-check-dev-postgres.c43ekyi6yiie.us-east-1.rds.amazonaws.com,portNumber=5432,localPortNumber=5432
```

2. 다른 터미널에서 연결 정보를 설정합니다. 비밀번호는 AWS 콘솔 Secrets Manager에서 찾고, 화면에 보이지 않게 입력해 명령 기록에 남기지 않습니다.

```powershell
cd backend
$env:PGHOST = "localhost"; $env:PGPORT = "5432"; $env:PGDATABASE = "pill"; $env:PGUSER = "pill_admin"; $env:PGSSLMODE = "require"
$p = Read-Host "RDS 비밀번호" -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))
```

3. 위의 점검 명령을 실행합니다. 이 계정은 팀이 공유하는 마스터 계정이므로, v2가 하는 읽기 전용 조회 외에는 아무것도 하지 않도록 주의하세요. 끝나면 `Remove-Item Env:PGPASSWORD`로 지웁니다.

- 연결은 `localhost`라서 인증서 호스트명 검사(`verify-full`)가 맞지 않아 `PGSSLMODE=require`를 씁니다. 이 설정은 이 방식(터널)에서만 쓰세요.
- 병용금기는 `dev_data/contraindication.sqlite`가 있으면 그 파일로, 없으면 RDS `gold.drug_contraindication`으로 켜집니다(로컬 DB에 `gold`가 없으면 `LLM_V2_CONTRA_SOURCE=off`).

## 테스트

```powershell
cd backend
uv run pytest app/llm/v2/tests
```

`pyproject.toml`의 `testpaths`가 `tests`뿐이라 경로를 직접 지정해야 합니다. DB·AWS·Claude 없이 가짜 객체로 돌아갑니다.

## 확인된 것 / 확인되지 않은 것

확인됨(작성 환경에서 실행):
- 위 테스트 196개가 통과했다(변이 확인: 근거 검사·허용 도구 검사를 지우면 해당 테스트가 실패한다).
- 자격증명 정책(`aws_auth.py`)은 가짜 세션으로 엄격·완화·EC2 감지를, 설정 기본값은 `PGHOST` 유무에 따른 전환을 시험했다(정책 검사를 지우거나 항상 완화로 바꾸면 해당 테스트가 실패한다). **실제 EC2의 `iam-role` 판정과 DMI 감지는 이 환경에서 확인하지 못했다.**
- 건강기능식품 주의사항(`check_contraindication`)은 가짜 DB로 문단 단위 자르기·예산 분배·생략 안내·주의사항 없음·이름 검색(의약품+건강기능식품)을 시험했다(예산 검사나 중복 제거를 지우면 해당 테스트가 실패한다). 원본 건강기능식품 데이터(`data/health_food`)의 '섭취 시 주의사항'은 45,938개 제품 중 44,270개(96%)에 있고 글자 수가 중앙값 140자·99% 533자·최대 1,242자라 6,000자 예산 안에 거의 항상 들어간다. **다만 파이프라인이 이 값을 DB에서 어떤 문단으로 나눠 `precautions`에 넣었는지(문단 개수)는 이 환경에서 확인하지 못했다.**
- HTTP API(`api.py`)는 가짜 에이전트로 요청 검증·인증·상태 코드·동시 요청 제한·오류 비노출을 시험했다. 단, **`build_agent`가 실제 DB·Bedrock으로 앱을 띄우는 경로는 작성 환경에 SQLAlchemy가 없어 시험하지 못했다**(에이전트 자체는 평가 스크립트에서 실제로 동작을 확인).
- 검색 SQL을 실제 PostgreSQL 16에서 `vector_pipeline/sql/init.sql` 스키마로 실행했다: 이름 단계(exact/prefix/contains), `%`·`_` 이스케이프, 악의적 입력 무해, 제품 범위 한정, 공유 본문의 `source_count`, 읽기 전용 트랜잭션의 쓰기 거부, 괄호 이름 처리(괄호 포함/제외 입력, 전각 괄호, 공백, 근사 일치, 후보 여럿 → 되묻기, `product_key` 지정). 제품명 변형 평가(`name_eval`)의 집계 로직도 같은 DB로 시험했다(3개 제품, 변형 6종). 병용금기 도구는 실제 `data.parquet`에서 만든 인덱스로, 같은 PostgreSQL에 적재한 실제 제품명·`item_seq`와 함께 시험했다(실제 규칙 쌍 9개 모두 확인, 규칙 없는 대조군 2쌍은 규칙 없음, 이름이 갈리는 입력은 되묻기). 단, **pgvector는 없어서** `vector` 타입과 `<=>`는 같은 모양의 대체물로 시험했다.

확인 안 됨(첫 실제 실행에서 확인 필요):
1. 진짜 pgvector에서 `CAST(:q AS vector)` 문자열 바인딩(asyncpg가 `vector` 파라미터를 텍스트로 보내는지)과 SQLAlchemy `async_creator` 경로. 로컬 compose DB에서 가장 먼저 확인하세요.
2. Bedrock 엔드포인트(InvokeModel / Mantle)의 **도구 호출 지원**과 모델 ID(기본값은 v1에서 가져온 `us.anthropic.claude-*-5-5`). EC2 역할에는 `bedrock:InvokeModel`만 있어 `bedrock`이 기본이며, `mantle`은 IAM 추가가 필요하다.
3. 한국어 질문의 실제 검색 품질(평가 스크립트로 측정), pg_trgm의 한글 동작(DB 로케일 의존), 전체(제품명 없는) 검색의 지연시간.
4. 응급·위기 감지는 정규식 기반 보조 장치라 놓치는 표현이 있을 수 있다. 상담전화 번호(109)는 배포 전에 최신 여부를 확인하세요.

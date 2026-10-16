# 의약품·건강기능식품 통합 벡터 파이프라인 v2.1

이 폴더만으로 실버 Parquet을 검색 문서로 가공하고, 임베딩을 생성·보존한 뒤 PostgreSQL RDS에 적재합니다. 기존 `infra/terraform`의 EC2·RDS·S3·Secrets Manager 구성을 사용하며 다른 폴더를 변경하지 않습니다.

## 기존 인프라 연결 (EC2)

저장소 설정은 us-east-1, EC2 역할 인증, 프라이빗 RDS 데이터베이스 `pill`, 버전 관리되는 데이터 버킷입니다. 이는 코드 확인 결과이며 실제 배포 상태·S3 객체·연결 성공을 확인한 것은 아닙니다. `pipeline/silver/build.py`는 로컬 `s3/silver/`에 파일을 생성합니다. 확인한 수집 진입점에는 S3 업로드 코드가 없으므로 별도 업로드 단계에서 Parquet과 메타데이터를 먼저 올리고 **`silver/_latest.json`을 마지막에** 올려야 합니다. 공개한 snapshot 경로는 덮어쓰지 않아야 합니다.

1. `settings.toml`에 제공된 RDS 호스트·DB 이름·시크릿 이름과 us-east-1 리전이 설정되어 있습니다. `.env`는 필요하지 않습니다.
2. EC2 역할에 해당 시크릿의 `secretsmanager:GetSecretValue` 권한이 있어야 합니다. S3 버킷은 `prepare-silver --bucket 실제버킷이름`으로 전달합니다.
3. RDS CA 번들을 `vector_pipeline/certs/global-bundle.pem`에 준비합니다. `output/`은 컨테이너 UID 10001이 쓸 수 있어야 합니다.
4. 다음 명령은 `vector_pipeline/`에서 실행합니다. EC2용 override는 Linux host 네트워크를 사용하여 기존 IMDSv2 hop limit에서도 역할 인증에 접근합니다. 포트를 열거나 서비스를 상시 실행하지 않습니다.

```sh
docker compose -f compose.yaml -f compose.ec2.yaml build
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline prepare-silver --bucket 실제버킷이름 --output /app/output/silver-run-001
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline validate --input /app/output/silver-run-001
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline embed --input /app/output/silver-run-001 --cache /app/output/embedding-cache.sqlite
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline init-db
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline ingest --input /app/output/silver-run-001 --cache /app/output/embedding-cache.sqlite
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline create-index
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline ingest --input /app/output/silver-run-001 --cache /app/output/embedding-cache.sqlite --publish
```

각 명령이 성공한 뒤 다음 단계로 진행하세요. `prepare-silver`는 완료 포인터를 한 번 읽어 두 제품 테이블의 날짜를 고정하고 Parquet 행의 snapshot도 확인합니다. `--snapshot YYYY-MM-DD`는 현재 포인터가 예상 날짜인지 확인하는 옵션입니다. 과거 스냅샷 재처리는 기존 `prepare --drug ... --health-food ...`를 사용합니다. 재실행할 때 완성된 bundle은 재생성하지 않고 embed/ingest부터 재개합니다.

`settings.toml`의 시크릿 이름으로 연결마다 username/password를 조회합니다. 비밀번호를 파일에 저장하지 않습니다. DB 설정은 이 파일만 사용하며 PG*/DB_* 환경변수로 덮어쓰지 않습니다. AWS 인증은 EC2 IAM 역할을 사용합니다.

인프라 주석의 `rag`와 달리 이 파이프라인은 기존 **`product_search` 스키마를 유지**합니다. `gold` 및 백엔드 테이블을 변경하지 않으며 스키마 이름 자동 변경도 하지 않습니다. RDS 실제 사양·확장 권한·Titan 접근 권한·검색 지연시간은 EC2에서 별도 확인해야 합니다.

```text
로컬/S3 Parquet
  → prepare: 공통 본문 중복 제거 + 제품 연결 분리
  → validate: 전체 파일·본문·참조 검증
  → embed: 제한된 병렬 호출 → 영구 SQLite 임베딩 캐시
  → ingest: RDS에 COPY 배치 적재·체크포인트 저장
  → create-index: HNSW 생성
  → ingest --publish: 완료된 전체 스냅샷을 원자적으로 활성화
```

## v2의 주요 변경

1. **DUR 문장화:** 내부 JSON을 임베딩하지 않습니다. 성분·제형·연령·등급·최대용량·최대기간·주의내용·비고만 읽을 수 있는 텍스트로 만듭니다. 규칙 ID·코드·연결 상태는 링크의 `metadata`에 유지합니다. 서로 다른 하위 규칙은 분리하며 긴 문장의 각 후속 청크에도 조건을 반복합니다. 길이 한도 초과 규칙은 `rejects.jsonl`에 원문·조건·제품 키와 함께 격리하고 나머지는 계속 처리합니다. 예산 301자/중첩 150자의 경계 오류도 구체적인 DUR 오류로 처리합니다.
2. **본문 공유:** 제품명·업체명은 `overview`에만 임베딩하고 나머지는 메타데이터로 보존합니다. 동일 제품군·정보 유형의 동일 본문은 여러 제품이 벡터 하나를 공유합니다. 본문 내부에 원래 포함된 제품명은 임의로 지우지 않습니다.
3. **짧은 조항 병합:** 같은 제품의 동일 원문 필드 안에서 인접한 짧은 조항을 합칩니다. 기본 병합 목표 900자, 본문 상한 1,800자, 긴 본문 분할 중첩 150자입니다. 문자 수이며 토큰 수가 아닙니다. 모든 제목과 원본 참조를 유지합니다. DUR의 서로 다른 조건은 병합하지 않습니다.
4. **실패 후 재개:** 임베딩 성공 응답을 SQLite에 float32 BLOB으로 즉시 커밋합니다. DB 연결과 분리되며 재실행 시 성공분은 재사용합니다. 강제 종료 직전 응답이 도착했지만 아직 커밋하지 못한 호출은 다시 발생할 수 있습니다.
5. **제한된 병렬 처리:** 기본 동시 API 호출 4개, 최대 32개. 문서별 입력 오류는 캐시에 기록하고 다음 문서를 계속 처리합니다. 권한·자격증명·서비스/연결 장애는 문서 결함과 구분하여 중단합니다. Botocore 재시도를 사용하며 실제 할당량에 맞춰 workers를 설정해야 합니다.
6. **배치 적재·공개 분리:** DB에 배치별로 커밋하며 같은 트랜잭션에서 체크포인트를 기록합니다. 임시 테이블은 한 배치만 담습니다. 전체 스냅샷 임시 벡터 복제는 없습니다. 실패한 run의 링크는 활성 검색에서 제외됩니다. 완성 후 포인터 한 건을 바꿔 공개합니다.
7. **인덱스 후생성:** `init-db`는 HNSW를 만들지 않습니다. 초기 적재 후 `create-index`를 별도로 실행합니다. 이후 증분 적재 시 기존 인덱스는 유지·갱신됩니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `build_documents.py`, `chunking.py` | 문장화·병합·분할·제품 연결 생성 |
| `bundle.py` | v2 JSONL 출력, 중복 제거, 파일·참조 검증 |
| `read_s3.py` | 로컬/S3 읽기, S3 version/ETag 고정 |
| `embedding.py`, `embed_pipeline.py` | Bedrock 어댑터·제한된 병렬 실행 |
| `cache.py` | 모델·차원별 영구 SQLite 임베딩 캐시 |
| `vector_store.py` | 배치 COPY·재개·활성 스냅샷 전환 |
| `search.py` | 제품명 식별 후 필터를 적용한 exact 벡터 검색 |
| `lifecycle.py` | 이력 기록을 동반한 롤백, dry-run 기반 보존 정책 정리 |
| `sql/init.sql`, `sql/create_index.sql` | 스키마와 HNSW 생성을 분리 |
| `run.py` | 명령행 진입점 |

## 지금 실행: AWS·RDS 없이 문서 생성

ZIP을 풀고 각 `data.parquet` 경로를 지정합니다. PowerShell에서는 명령을 한 줄로 실행하세요.

```sh
cd vector_pipeline
python -m venv .venv
# Linux: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py prepare --drug /path/drug/data.parquet --health-food /path/health/data.parquet --output output/sample-v2 --limit 100
python run.py validate --input output/sample-v2
python -m unittest discover -s tests -v
```

전체 데이터는 `--limit` 없이 새 출력 폴더로 생성합니다. 출력물:

- `documents.jsonl`: 고유 본문·본문 해시·제품군·정보 유형. **임베딩 호출 대상**입니다.
- `links.jsonl`: 제품 ID·제품명·업체·본문 해시·원본 참조·규칙 메타데이터·판매 상태·스냅샷. 벡터를 갖지 않습니다.
- `rejects.jsonl`: 길이 한도 초과로 격리한 DUR 규칙의 원문·조건·출처·오류. 정상이라면 빈 파일입니다.
- `manifest.json`: 파일 SHA-256, 원본/처리 제품 수, 고유 문서/연결 수, 본문 문자 수, 전체/샘플 구분.

두 소스의 스냅샷이 같아야 합니다. 기본키 중복·참조 누락·해시 불일치가 있으면 거부합니다. 변환 실패 시 부분 파일을 정리하고 완료 결과는 덮어쓰지 않습니다. `embedding_characters`는 토큰 수나 가격이 아닙니다.

격리된 규칙이 하나라도 있으면 manifest의 `rejected_rules`에 기록하고 `complete=false`로 표시합니다. 다른 제품·문서는 정상적으로 생성·검증할 수 있지만 `--publish`는 거부합니다. 원문을 검토해 조건 길이/전처리를 수정한 뒤 새 폴더에 다시 prepare 해야 합니다. 누락을 정상 결과로 숨기거나 자동 공개하지 않습니다.

## Docker 준비

```sh
# settings.toml 사용: .env 복사 불필요
mkdir -p input output certs
sudo chown 10001:10001 output
docker compose build
docker compose run --rm pipeline prepare --drug /input/drug.parquet --health-food /input/health.parquet --output /app/output/full-v2
docker compose run --rm pipeline validate --input /app/output/full-v2
```

Linux EC2 기준입니다. `input`에는 원본 Parquet, `output`에는 bundle과 SQLite 캐시를 둡니다. **`output` bind mount를 유지해야 컨테이너 재생성 후에도 재개할 수 있습니다.** 캐시를 EBS 등 지속되는 로컬 디스크에 두세요. SQLite WAL은 네트워크 파일시스템 공유용이 아닙니다. 캐시 DB를 백업할 때는 작업을 중지하거나 SQLite backup API를 사용해야 합니다.

Compose는 `.env`를 컨테이너에 주입하지 않습니다. `settings.toml`을 읽기 전용 마운트합니다. 로컬 Python도 같은 파일을 읽으며 로컬 실행 시 인증서 경로는 로컬 경로로 수정해야 합니다.

## AWS 준비 후 임베딩

S3와 Secrets Manager 리전은 `settings.toml`의 aws.region을 사용합니다. 임베딩도 기본적으로 같은 리전의 Titan V2 1,024차원을 사용합니다. 임베딩 전용 환경변수 오버라이드는 호환성을 위해 유지합니다.

```sh
docker compose run --rm pipeline embed --input /app/output/full-v2 --cache /app/output/embedding-cache.sqlite --workers 4 --batch-size 128
```

성공 응답은 즉시 저장됩니다. 입력 오류가 난 문서는 SQLite `failures` 테이블에 본문 해시·오류 코드·시도 횟수를 기록하며, 종료 시 캐시 옆 `embedding-cache.failures.jsonl`에도 내보냅니다. 원문은 해시로 `documents.jsonl`에서 확인할 수 있습니다. 같은 명령을 다시 실행하면 기록된 실패는 건너뛰고 미처리 문서를 진행합니다. 해결 후 실패만 포함해 다시 시도하려면:

```sh
docker compose run --rm pipeline embed --input /app/output/full-v2 --cache /app/output/embedding-cache.sqlite --retry-failed
```

미해결 문서가 있으면 다른 문서를 모두 처리한 후 종료 코드 **2**와 `complete=false`를 반환합니다. 성공은 0, 권한/DB/디스크 등 실행 오류는 비정상 종료입니다. `ingest`는 필요한 임베딩이 모두 존재해야 완료할 수 있으므로 누락된 벡터를 자동 공개하지 않습니다. 권한/연결 오류는 문서 실패 목록에 넣지 않으므로 환경 복구 후 기본 명령으로 재시도할 수 있습니다.

모델 ID·차원·정규화 설정이 다르면 별도 캐시 키를 사용합니다. `embed`는 DB에 연결하지 않습니다. 캐시가 없지만 DB에 벡터가 있는 경우 DB에서 캐시를 가져오지는 않습니다. `search --query`도 질문 임베딩을 위해 Bedrock을 호출합니다.

S3를 직접 읽는 경우:

```sh
docker compose run --rm pipeline prepare --drug s3://BUCKET/silver/drug_product/snapshot=2026-10-13/data.parquet --health-food s3://BUCKET/silver/health_food_product/snapshot=2026-10-13/data.parquet --output /app/output/from-s3-v2
```

실행 위치는 **EC2 Docker**입니다. 기존 EC2 역할의 `s3:GetObject`, `bedrock:InvokeModel`, `secretsmanager:GetSecretValue`를 사용합니다. S3 현재 객체를 ETag 조건으로 읽고 응답의 VersionId를 기록하므로 `s3:GetObjectVersion` 추가 권한은 필요하지 않습니다. HEAD 이후 내용이 바뀌면 다운로드를 중단합니다. 이 폴더는 IAM·보안 그룹을 변경하지 않습니다.

## RDS 준비 후 적재

`settings.toml`의 DB 설정을 사용하고 RDS CA 번들을 `certs/global-bundle.pem`에 준비합니다. TLS는 `verify-full`입니다. RDS가 실행 중이어야 하며 EC2에서 RDS 5432 포트에 접근 가능해야 합니다.

```sh
docker compose run --rm pipeline init-db
docker compose run --rm pipeline ingest --input /app/output/full-v2 --cache /app/output/embedding-cache.sqlite --batch-size 128
docker compose run --rm pipeline create-index
docker compose run --rm pipeline ingest --input /app/output/full-v2 --cache /app/output/embedding-cache.sqlite --publish
```

두 번째 ingest는 이미 완료된 run을 확인하고 공개 포인터만 전환합니다. 장애로 적재가 중단되면 동일 명령으로 재실행하세요. 저장된 문서·링크 행 위치부터 계속하며 데이터와 진행 위치는 함께 커밋됩니다. 본문 해시가 이미 DB에 있으면 벡터를 중복 적재하지 않습니다. 한 번에 실행되는 DB 적재/인덱스 작업은 advisory lock으로 제한합니다.

샘플·격리된 규칙이 있는 bundle은 적재 가능하지만 `--publish`는 거부합니다. 공개 시 두 제품군의 전체 스냅샷이 한 번에 교체되므로 새 스냅샷에서 빠진 제품은 검색에서 제외됩니다. 이전 run·벡터는 보존되며 아래 rollback/prune 명령으로 관리합니다.

## 단일 벡터 인덱스와 검색 계약

| DB 객체 | 저장 내용 |
|---|---|
| `product_vectors` | 고유 본문당 벡터 하나. 두 제품군을 함께 저장 |
| `product_links` | 본문과 제품의 다대다 연결, run별 출처·조건·상태 |
| `ingestion_runs` | 적재 진행 위치와 완료 상태 |
| `active_snapshot` | 현재 공개된 run 한 건 |
| `active_vectors`, `active_product_links` | 공개된 데이터만 조회하는 뷰 |

`search.py`와 CLI가 제품명 식별 → 관련 청크 검색을 구현합니다. `overview` 행에 한정된 제품명 B-tree(정확/접두어)와 pg_trgm GIN(3자 이상 포함 검색) 인덱스를 추가했습니다. 일반 문서 88만 행을 이름 조회 대상으로 삼지 않습니다. 기존 v2 DB는 `init-db`를 다시 실행하여 추가 인덱스·상태·이력 테이블을 설치해야 합니다. pg_trgm 확장 생성 권한이 필요합니다.

```sh
# 제품 후보만 조회: 임베딩 호출 없음
docker compose run --rm pipeline search --product-name 타이레놀 --product-type drug
# 이름으로 제품을 먼저 찾고 해당 제품들의 복용법만 검색
docker compose run --rm pipeline search --product-name 타이레놀 --query "복용 방법과 용량" --section-type usage --top-k 5
# 품목 ID로 범위를 정확히 지정 (여러 --product-key도 가능)
docker compose run --rm pipeline search --product-key drug:품목번호 --query "임부 주의사항" --section-type precautions
```

자유문장에서 제품명을 자동 추출하지는 않습니다. 품목명 질문은 호출자가 `--product-name` 또는 `--product-key`로 제품 범위를 전달해야 합니다. 이름이 없으면 전체로 확대하지 않고 빈 결과를 반환하며, 이름 후보가 20개를 넘으면 이름/ID를 구체화하도록 오류를 반환합니다. 이름만 조회한 결과는 제품 키·업체·종류를 포함합니다.

검색은 활성 run과 제품/유형 필터를 먼저 적용한 후보 집합을 MATERIALIZED CTE로 확정한 후 **exact 코사인 순위**를 계산합니다. HNSW 후보를 필터링하는 방식이 아니므로 ANN에 의한 후보 누락을 피합니다. 고유 본문을 먼저 top-k로 고른 뒤 제품 출처를 연결하여 중복 제네릭이 top-k를 채우지 않게 합니다. 출처는 본문당 최대 50건과 전체 `source_count`를 반환합니다. 검색 중 공개/정리가 진행돼도 REPEATABLE READ 트랜잭션으로 동일 스냅샷을 읽습니다.

전체 범위 exact 검색은 비싸거나 느릴 수 있습니다. 이 경로는 재현율을 우선한 기준 구현이며, 지연시간·쿼리 계획은 RDS에서 별도 측정해야 합니다. HNSW 인덱스는 향후 ANN 최적화용으로 남아 있지만 이 exact 검색에서는 사용하지 않습니다. 백엔드 API는 수정하지 않았습니다.

## 롤백 및 보존 기간 정리

일반 publish는 과거 스냅샷으로의 이동을 계속 차단합니다. 명시적 rollback만 검증된 완료 run으로 이동하며 사유와 전후 run을 `publication_events`에 같은 트랜잭션으로 기록합니다.

```sh
docker compose run --rm pipeline rollback --run-id 이전runID --reason "최근 데이터 검증 실패로 복구"
# 기본은 삭제 없이 계획만 출력
docker compose run --rm pipeline prune --keep-last 2 --older-than-days 30
# 검토한 정책으로 실제 DB 정리
docker compose run --rm pipeline prune --keep-last 2 --older-than-days 30 --apply
```

활성 run 및 최근 완료 run N개는 보존합니다(완료/갱신 시각 기준). 그 외 기간이 지난 완료 run을 배치 삭제하고, 모든 보존 run에서 참조되지 않는 벡터를 정리합니다. 미완료 run은 기본 보존하며 `--include-incomplete`를 명시해야 기간이 지난 미완료 run도 대상이 됩니다. loading run이 남아 있으면 재개에 필요한 벡터 보호를 위해 고아 벡터 정리는 보류합니다. 로컬 SQLite 캐시·bundle은 삭제하지 않습니다.

정리 중인 run은 `pruning`으로 표시되어 적재 재개/롤백이 차단됩니다. 중단된 정리는 같은 prune 명령으로 이어서 처리할 수 있습니다. 완료된 삭제는 되돌릴 수 없으며 제거한 run으로는 롤백할 수 없습니다. DB 삭제는 공간 재사용을 가능하게 하지만 파일 크기를 즉시 줄이진 않습니다. 실제 삭제·롤백 명령은 이번 로컬 검증에서 실행하지 않았습니다.

## 이전 v1과의 호환성

v1의 `chunks.jsonl` 및 `product_vectors` 구조와 호환되지 않습니다. 기존 `output/full`은 그대로 두고 `output/full-v2` 등 새 폴더에서 prepare 하세요. v1 DB를 감지하면 초기화를 거부하며 기존 테이블·인덱스를 삭제하지 않습니다. 이미 v1 DB를 운영한다면 별도 DB/스키마로 구축하고 검증 후 전환하는 작업이 필요합니다. 자동 마이그레이션은 제공하지 않습니다.

## 검증 범위

테스트는 DUR 문장화·조건 반복·대안 분리, 짧은 조항 병합·출처 보존, 제품 간 본문 공유, bundle 무결성, 영구 캐시 재개·모델 격리·동시 호출 제한, 배치와 체크포인트의 트랜잭션 경계를 검증합니다. DB 트랜잭션 테스트는 모의 연결을 사용합니다. 실제 Bedrock/RDS 연동·Docker 이미지 빌드·성능·검색 품질은 아직 검증하지 않았습니다.

2026-10-15 로컬 검증: 테스트 **36개 통과**, Python 구문 검사와 Docker Compose 설정 검사 통과. 실패 문서 격리·명시적 재시도, DUR 조건 예산 301/302자 경계, 제품명 조회 및 검색 범위, 롤백·정리 보호 조건도 검증했습니다. DB 동작 검증은 모의 연결 기준입니다.

제공된 전체 제품 **85,740개**를 `output/full-v2.1/`로 다시 변환하고 파일 해시·본문 해시·중복·제품 수·출처 연결을 검증했습니다. 고유 문서 **334,928개**, 제품 연결 **877,696개**, 격리된 DUR 규칙 **0개**이며 완전한 bundle입니다. 아래 크기 비교는 기존 v1/v2 산출물의 측정값입니다.

| 항목 | v1 | v2 |
|---|---:|---:|
| 제품별 청크/연결 수 | 1,148,978 | 877,696 |
| 고유 임베딩 입력 수 | 1,148,323 | 334,928 |
| JSONL 전체 크기 | 1,942,544,218바이트 | 961,118,831바이트 |

고유 입력은 **70.8% 감소**, 제품별 청크/연결은 **23.6% 감소**했습니다. v2 고유 본문의 총 길이는 151,451,082자입니다. 고유 벡터 334,928개의 1,024차원 float32 값만 산정하면 약 1.37GB이며 실제 DB 크기가 아닙니다. 이 검증에서는 유료 임베딩 호출이나 RDS 쓰기를 실행하지 않았습니다. v1 결과도 삭제하지 않았습니다.

RDS 사양은 이 폴더에서 결정하지 않습니다. 고유 벡터 수 × 차원 × 4바이트는 벡터 값만의 크기이고, 본문·연결·HNSW·WAL·여유 공간을 추가로 산정해야 합니다. 초기 HNSW는 적재 후 생성하며 실제 사양은 실측 후 선택하세요.

- [Titan V2 모델 규격](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [pgvector 적재 및 인덱싱](https://github.com/pgvector/pgvector#loading)

## 환경변수 없이 DB 연결 확인

RDS를 시작하고 Available 상태에서 EC2의 `vector_pipeline/` 디렉터리에서 실행하세요. 인증서가 준비되어 있어야 합니다. 다음 검사는 테이블을 만들거나 데이터를 변경하지 않습니다.

```sh
docker compose -f compose.yaml -f compose.ec2.yaml build
docker compose -f compose.yaml -f compose.ec2.yaml run --rm pipeline check-db
```

이번 변경은 모의 Secret 응답을 이용해 검증했습니다. 실제 RDS 시작·접속은 수행하지 않았습니다.

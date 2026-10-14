# 의약품·건강기능식품 통합 벡터 파이프라인 v2

이 폴더만으로 실버 Parquet을 검색 문서로 가공하고, 임베딩을 생성·보존한 뒤 향후 PostgreSQL RDS에 적재합니다. 골드·API·EC2/RDS/IAM 생성 코드는 포함하지 않습니다. 인프라는 별도로 준비합니다.

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

1. **DUR 문장화:** 내부 JSON을 임베딩하지 않습니다. 성분·제형·연령·등급·최대용량·최대기간·주의내용·비고만 읽을 수 있는 텍스트로 만듭니다. 규칙 ID·코드·연결 상태는 링크의 `metadata`에 유지합니다. 서로 다른 하위 규칙은 분리하며 긴 문장의 각 후속 청크에도 조건을 반복합니다. 조건 자체가 한도보다 길면 잘라 버리지 않고 실패합니다.
2. **본문 공유:** 제품명·업체명은 `overview`에만 임베딩하고 나머지는 메타데이터로 보존합니다. 동일 제품군·정보 유형의 동일 본문은 여러 제품이 벡터 하나를 공유합니다. 본문 내부에 원래 포함된 제품명은 임의로 지우지 않습니다.
3. **짧은 조항 병합:** 같은 제품의 동일 원문 필드 안에서 인접한 짧은 조항을 합칩니다. 기본 병합 목표 900자, 본문 상한 1,800자, 긴 본문 분할 중첩 150자입니다. 문자 수이며 토큰 수가 아닙니다. 모든 제목과 원본 참조를 유지합니다. DUR의 서로 다른 조건은 병합하지 않습니다.
4. **실패 후 재개:** 임베딩 성공 응답을 SQLite에 float32 BLOB으로 즉시 커밋합니다. DB 연결과 분리되며 재실행 시 성공분은 재사용합니다. 강제 종료 직전 응답이 도착했지만 아직 커밋하지 못한 호출은 다시 발생할 수 있습니다.
5. **제한된 병렬 처리:** 기본 동시 API 호출 4개, 최대 32개. 실패하면 새 호출을 중단하고 진행 중 성공 응답까지 저장한 뒤 실패를 보고합니다. 리전·계정 할당량에 맞춰 낮추거나 높여야 합니다. Botocore 재시도를 사용합니다.
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
- `manifest.json`: 파일 SHA-256, 원본/처리 제품 수, 고유 문서/연결 수, 본문 문자 수, 전체/샘플 구분.

두 소스의 스냅샷이 같아야 합니다. 기본키 중복·참조 누락·해시 불일치가 있으면 거부합니다. 변환 실패 시 부분 파일을 정리하고 완료 결과는 덮어쓰지 않습니다. `embedding_characters`는 토큰 수나 가격이 아닙니다.

## Docker 준비

```sh
cp .env.example .env
mkdir -p input output certs
sudo chown 10001:10001 output
docker compose build
docker compose run --rm pipeline prepare --drug /input/drug.parquet --health-food /input/health.parquet --output /app/output/full-v2
docker compose run --rm pipeline validate --input /app/output/full-v2
```

Linux EC2 기준입니다. `input`에는 원본 Parquet, `output`에는 bundle과 SQLite 캐시를 둡니다. **`output` bind mount를 유지해야 컨테이너 재생성 후에도 재개할 수 있습니다.** 캐시를 EBS 등 지속되는 로컬 디스크에 두세요. SQLite WAL은 네트워크 파일시스템 공유용이 아닙니다. 캐시 DB를 백업할 때는 작업을 중지하거나 SQLite backup API를 사용해야 합니다.

`.env`는 Compose만 자동으로 읽습니다. 로컬 Python은 환경변수를 직접 설정하세요. 실제 배포 리전을 추정하지 않도록 AWS_REGION/BEDROCK_REGION 기본값은 비워 두었습니다. 로컬 prepare/validate/tests에는 리전이 필요하지 않습니다.

## AWS 준비 후 임베딩

`AWS_REGION`(S3), `BEDROCK_REGION`(임베딩)을 명시하세요. 현재 어댑터는 Titan Text Embeddings V2만 지원하며 기본 1,024차원, 256/512차원도 설정할 수 있습니다. 다른 모델을 지정하면 명시적으로 실패합니다. 실제 한국어 검색 품질은 별도 평가가 필요합니다.

```sh
docker compose run --rm pipeline embed --input /app/output/full-v2 --cache /app/output/embedding-cache.sqlite --workers 4 --batch-size 128
```

실패하면 **동일 명령과 동일 캐시 경로**로 재실행합니다. 모델 ID·차원·정규화 설정이 다르면 별도 캐시 키를 사용합니다. AWS 호출은 `embed`에서만 발생하고 DB 연결은 하지 않습니다. 캐시가 없지만 DB에 벡터가 있는 경우 `embed`가 DB 캐시를 가져오지는 않습니다. 로컬 캐시를 유지하세요.

S3를 직접 읽는 경우:

```sh
docker compose run --rm pipeline prepare --drug s3://BUCKET/silver/drug_product/snapshot=2026-10-13/data.parquet --health-food s3://BUCKET/silver/health_food_product/snapshot=2026-10-13/data.parquet --output /app/output/from-s3-v2
```

예정 실행 위치는 **EC2 Docker**입니다. 기존 ECS 태스크 역할을 사용한다고 가정하지 않습니다. EC2 인스턴스 역할에는 지정 Silver 객체의 `s3:GetObject`, 버전 객체의 `s3:GetObjectVersion`, 사용 모델의 `bedrock:InvokeModel` 권한이 필요합니다. KMS 암호화 시 복호화 권한도 필요합니다. 컨테이너의 IMDSv2 자격증명 접근 및 S3/Bedrock 네트워크 경로는 인프라 준비 단계에서 확인하세요. 이 폴더는 IAM·보안 그룹을 변경하지 않습니다.

## RDS 준비 후 적재

`PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`를 설정하고 RDS CA 번들을 `certs/global-bundle.pem`에 준비합니다. 기본 TLS는 `verify-full`입니다. 프라이빗 RDS에 접근 가능한 EC2 네트워크·보안 그룹이 필요하며 로컬 Compose가 자동으로 터널을 만들지는 않습니다.

```sh
docker compose run --rm pipeline init-db
docker compose run --rm pipeline ingest --input /app/output/full-v2 --cache /app/output/embedding-cache.sqlite --batch-size 128
docker compose run --rm pipeline create-index
docker compose run --rm pipeline ingest --input /app/output/full-v2 --cache /app/output/embedding-cache.sqlite --publish
```

두 번째 ingest는 이미 완료된 run을 확인하고 공개 포인터만 전환합니다. 장애로 적재가 중단되면 동일 명령으로 재실행하세요. 저장된 문서·링크 행 위치부터 계속하며 데이터와 진행 위치는 함께 커밋됩니다. 본문 해시가 이미 DB에 있으면 벡터를 중복 적재하지 않습니다. 한 번에 실행되는 DB 적재/인덱스 작업은 advisory lock으로 제한합니다.

샘플은 적재 가능하지만 `--publish`는 거부합니다. 공개 시 두 제품군의 전체 스냅샷이 한 번에 교체되므로 새 스냅샷에서 빠진 제품은 검색에서 제외됩니다. 이전 run·사용하지 않는 벡터는 자동 삭제하지 않아 롤백·검토가 가능하지만 저장 공간은 늘어납니다. 보존 기간에 따른 정리는 별도로 설계해야 합니다.

## 단일 벡터 인덱스와 검색 계약

| DB 객체 | 저장 내용 |
|---|---|
| `product_vectors` | 고유 본문당 벡터 하나. 두 제품군을 함께 저장 |
| `product_links` | 본문과 제품의 다대다 연결, run별 출처·조건·상태 |
| `ingestion_runs` | 적재 진행 위치와 완료 상태 |
| `active_snapshot` | 현재 공개된 run 한 건 |
| `active_vectors`, `active_product_links` | 공개된 데이터만 조회하는 뷰 |

**검색은 `active_vectors`에서 고유 본문을 먼저 top-k로 고른 뒤 `active_product_links`로 제품을 연결**해야 합니다. 링크를 먼저 JOIN하여 top-k를 뽑으면 동일 본문이 제네릭 수만큼 반복될 수 있습니다. 제품을 특정한 질문은 제품 키 조건을 후보 선택 전에 적용합니다. 품목명 검색은 overview 또는 제품 메타데이터 조회를 이용합니다.

주의: 미공개·이전 벡터도 기본 테이블에 남습니다. 기본 테이블을 필터 없이 검색하지 마세요. HNSW와 선택적인 필터 조합은 결과 부족·재현율 문제를 만들 수 있으므로 실제 검색 평가 및 필요 시 exact 검색/iterative scan 등을 후속 검색 구현에서 검토해야 합니다. 이 폴더는 검색 API를 구현하지 않습니다.

## 이전 v1과의 호환성

v1의 `chunks.jsonl` 및 `product_vectors` 구조와 호환되지 않습니다. 기존 `output/full`은 그대로 두고 `output/full-v2` 등 새 폴더에서 prepare 하세요. v1 DB를 감지하면 초기화를 거부하며 기존 테이블·인덱스를 삭제하지 않습니다. 이미 v1 DB를 운영한다면 별도 DB/스키마로 구축하고 검증 후 전환하는 작업이 필요합니다. 자동 마이그레이션은 제공하지 않습니다.

## 검증 범위

테스트는 DUR 문장화·조건 반복·대안 분리, 짧은 조항 병합·출처 보존, 제품 간 본문 공유, bundle 무결성, 영구 캐시 재개·모델 격리·동시 호출 제한, 배치와 체크포인트의 트랜잭션 경계를 검증합니다. DB 트랜잭션 테스트는 모의 연결을 사용합니다. 실제 Bedrock/RDS 연동·Docker 이미지 빌드·성능·검색 품질은 아직 검증하지 않았습니다.

2026-10-14 로컬 검증: 테스트 **24개 통과**, Python 구문 검사와 Docker Compose 설정 검사 통과. 제공된 전체 제품 85,740개를 `output/full-v2/`로 변환하고 파일 해시·본문 해시·중복·제품 수·출처 연결을 검증했습니다.

| 항목 | v1 | v2 |
|---|---:|---:|
| 제품별 청크/연결 수 | 1,148,978 | 877,696 |
| 고유 임베딩 입력 수 | 1,148,323 | 334,928 |
| JSONL 전체 크기 | 1,942,544,218바이트 | 961,118,831바이트 |

고유 입력은 **70.8% 감소**, 제품별 청크/연결은 **23.6% 감소**했습니다. v2 고유 본문의 총 길이는 151,451,082자입니다. 고유 벡터 334,928개의 1,024차원 float32 값만 산정하면 약 1.37GB이며 실제 DB 크기가 아닙니다. 이 검증에서는 유료 임베딩 호출이나 RDS 쓰기를 실행하지 않았습니다. v1 결과도 삭제하지 않았습니다.

RDS 사양은 이 폴더에서 결정하지 않습니다. 고유 벡터 수 × 차원 × 4바이트는 벡터 값만의 크기이고, 본문·연결·HNSW·WAL·여유 공간을 추가로 산정해야 합니다. 초기 HNSW는 적재 후 생성하며 실제 사양은 실측 후 선택하세요.

- [Titan V2 모델 규격](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [pgvector 적재 및 인덱싱](https://github.com/pgvector/pgvector#loading)

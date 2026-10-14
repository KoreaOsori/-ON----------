# 통합 제품 벡터 파이프라인

의약품과 건강기능식품 실버 Parquet을 공통 검색 문서로 만들고, 나중에 Bedrock 임베딩을 생성하여 PostgreSQL의 **단일 `product_search.product_vectors` 테이블**에 적재합니다. 골드 적재·API·EC2/RDS 생성 코드는 포함하지 않습니다.

## 현재 바로 할 수 있는 작업

`prepare`와 `validate`는 로컬 Parquet만 있으면 AWS 자격증명과 DB 없이 실행됩니다. 가짜 벡터를 생성하지 않습니다. ZIP은 미리 풀고 `data.parquet` 경로를 지정합니다. PowerShell에서는 명령을 한 줄로 실행하세요.

```sh
cd vector_pipeline
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python run.py prepare --drug /path/drug_product/data.parquet --health-food /path/health_food_product/data.parquet --output output/sample --limit 100
python run.py validate --input output/sample
python -m unittest discover -s tests -v
```

전체 문서는 `--limit` 없이 **새로운 출력 폴더**에 생성합니다. 제품당 여러 청크가 만들어지므로 출력 JSONL은 원본 Parquet보다 커질 수 있습니다. 디스크 여유를 확보하세요.

```sh
python run.py prepare --drug /path/drug_product/data.parquet --health-food /path/health_food_product/data.parquet --output output/full
```

결과는 `chunks.jsonl`(검색 문서)과 `manifest.json`(두 소스의 행 수·스냅샷·청크 수·파일 SHA-256)입니다. 기본키 중복, 스냅샷 불일치, 필수값 누락은 실패로 처리합니다. 샘플은 `complete=false`이므로 전체 교체에 사용할 수 없습니다. 생성 중 실패한 부분 파일은 정리하며 기존 완료 결과는 덮어쓰지 않습니다.

## 파일 역할

| 파일 | 역할 |
|---|---|
| `read_s3.py` | 로컬/S3 Parquet 읽기, S3 버전 또는 ETag 고정 |
| `build_documents.py` | 두 제품군 → 공통 검색 문서 |
| `chunking.py` | 문자 수 기반 분할, 항목·문장 경계 우선 |
| `embedding.py` | Bedrock Titan V2 어댑터, 출력 벡터 검증 |
| `vector_store.py` | 변경 감지, 임시 적재, 원자적 반영 |
| `sql/init.sql` | 추후 pgvector 확장·테이블·HNSW 인덱스 생성 |
| `run.py` | prepare / validate / init-db / ingest 명령 |

## 문서 설계

- 공통 키: `drug:{item_seq}`, `health_food:{prdlst_report_no}`. 골드도 같은 연결 규칙을 사용해야 합니다.
- 공통 유형: overview, ingredients, benefits, usage, precautions, storage. 의약품에는 interactions, additional도 있습니다.
- 의약품 효능과 건강기능식품 기능성은 공통 검색 유형으로 묶지만 본문의 제품 종류를 유지합니다.
- 의약품 문서의 절 제목·항 제목·본문을 모두 사용합니다. 제목에만 내용이 있는 데이터도 보존합니다.
- DUR 규칙의 조건·연결 상태·하위 규칙을 보존합니다. null/빈 배열은 안전하다는 문장으로 변환하지 않습니다.
- 검색 텍스트는 원본에서 결정적으로 생성합니다. LLM 요약이나 추측을 추가하지 않습니다.
- 기본 본문 청크는 1,800자, 중첩 150자입니다. **토큰 수가 아닙니다.** 제품명·업체명 헤더가 각 청크에 붙습니다. 긴 조건이 분할될 수 있으므로 실제 서비스는 `source_ref`와 인접 청크 또는 골드 원문을 함께 확인해야 합니다.
- 판매 상태는 메타데이터로 유지합니다. 건강기능식품 판매 상태는 추정하지 않습니다.
- snapshot과 S3 경로는 본문 해시에 포함하지 않습니다. 날짜만 바뀌면 기존 임베딩을 재사용합니다.

## 나중에 Docker에서 실행

```sh
cp .env.example .env
mkdir -p input output certs
# input/drug.parquet, input/health_food.parquet 준비
# output은 컨테이너 UID 10001이 쓸 수 있게 설정
sudo chown 10001:10001 output
docker compose build
docker compose run --rm pipeline prepare --drug /input/drug.parquet --health-food /input/health_food.parquet --output /app/output/sample --limit 100
docker compose run --rm pipeline validate --input /app/output/sample
```

`.env`는 Compose가 읽습니다. **로컬 Python 실행은 `.env`를 자동 로드하지 않으므로** 필요한 값을 환경변수로 설정해야 합니다. 이미지에는 자격증명·출력 파일을 넣지 않습니다. Compose는 DB 컨테이너나 인프라를 생성하지 않습니다.

S3 직접 읽기도 지원합니다. 두 경로를 동일한 완료 스냅샷의 정확한 객체 경로로 지정합니다.

```sh
docker compose run --rm pipeline prepare --drug s3://BUCKET/silver/drug_product/snapshot=2026-10-13/data.parquet --health-food s3://BUCKET/silver/health_food_product/snapshot=2026-10-13/data.parquet --output /app/output/full
```

EC2에서는 인스턴스 역할에 지정 객체의 `s3:GetObject`(버전 사용 시 `s3:GetObjectVersion`)와 사용 모델의 `bedrock:InvokeModel` 권한을 부여해야 합니다. 고객 관리 KMS 키를 사용하면 복호화 권한도 필요합니다. 컨테이너에서 인스턴스 역할 자격증명에 접근할 수 있도록 IMDSv2 및 네트워크를 점검해야 합니다. 이 프로젝트는 IAM/IMDS 설정을 변경하지 않습니다.

## RDS 준비 후 실행할 작업

1. 해당 RDS 버전의 vector 확장 지원을 확인하고 `PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`를 설정합니다. 비밀번호는 Git에 저장하지 않습니다.
2. AWS RDS CA 번들을 `certs/global-bundle.pem`에 준비합니다. 기본 `verify-full`은 서버 인증서를 검증합니다.
3. 모델의 리전 접근과 한국어 검색 품질을 확인합니다. 현재 구현은 Titan Text Embeddings V2, 기본 1,024차원입니다. 다른 모델은 어댑터 구현이 필요합니다.
4. 확장·스키마 생성 권한이 있는 계정으로 초기화합니다. 런타임 적재 계정에는 필요한 DML·TEMP 권한만 부여할 수 있습니다.

```sh
docker compose run --rm pipeline init-db
docker compose run --rm pipeline ingest --input /app/output/full
```

`init-db`는 명시적으로 실행할 때만 RDS를 변경합니다. `ingest`는 Bedrock 사용료와 DB 쓰기를 발생시킵니다. 초기 대규모 임베딩은 순차 호출이므로 시간이 걸립니다. 모델/차원이 기존 테이블 설정과 다르면 적재를 거부합니다. 다른 모델로 전환할 때는 별도 인덱스 구축·검증·전환 절차가 필요합니다.

기본 적재는 입력에 포함된 제품을 갱신하고, 그 제품의 사라진 청크를 제거합니다. 입력에 없는 제품은 보존합니다. 전체 스냅샷에서 사라진 제품까지 제거하려면 검증된 전체 결과에 한해 다음 명령을 사용합니다.

```sh
docker compose run --rm pipeline ingest --input /app/output/full --replace-snapshot
```

임시 테이블에 모두 적재한 후 한 트랜잭션으로 반영하므로 실패 시 기존 검색 테이블을 유지합니다. 성공 이력도 같은 트랜잭션에 기록합니다. 동시 적재는 advisory lock으로 차단하고 이전 날짜로의 역행도 거부합니다. 기존 본문 해시와 임베딩 버전이 같으면 벡터를 재사용합니다. 단, 실패 실행에서 **새로 생성한 벡터는 영구 캐시하지 않으므로 재실행 시 해당 API 비용이 다시 발생**할 수 있습니다. 실행 중 출력 bundle을 수정하지 마세요.

## 검증 범위와 참고

단위 테스트는 제목만 있는 문서, 제품 유형 구분, DUR 조건 보존, 날짜 변경 시 해시 안정성, 청크 분할, 벡터 유효성, Parquet 변환·결과 검증·중복 거부를 확인합니다. 실제 Bedrock·RDS·Docker 배포 검증은 별도 환경이 준비된 후 수행해야 합니다. 한국어 검색 품질도 아직 평가 전입니다.

2026-10-14 로컬 검증 결과:

- 단위 테스트 12개 통과, Python 구문 검사 통과, Docker Compose 설정 검사 통과.
- 제공된 의약품 39,802개와 건강기능식품 45,938개 전체로 생성·검증 완료.
- 기본 설정에서 검색 청크 **1,148,978개**, JSONL **1,942,544,218바이트** 생성.
- 결과는 `output/full/`에 있으며 Git 및 Docker 빌드에서 제외됩니다.
- 청크 ID 중복, 본문 및 파일 해시, 제품 수, 스냅샷 일치 검사를 통과했습니다.
- 이는 실제 벡터 생성 건수가 아닌 임베딩 전 문서 건수입니다. Bedrock 호출 및 DB 적재는 실행하지 않았습니다. 전체 임베딩 전 샘플 검색 품질·중복·토큰 비용을 평가하세요.

- [AWS Titan V2 입력·출력 규격](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [pgvector SQL 및 인덱스 문서](https://github.com/pgvector/pgvector)

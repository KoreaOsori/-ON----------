-- gold 스키마: 앱이 바로 조회하는 판정용 테이블. silver(_latest.json) 에서 load.py 가 매번 통째로 다시 만든다.
-- 이 테이블들을 직접 고치지 말 것 (다음 적재 때 사라짐). 컬럼 설명은 docs/gold_table_spec.md
-- 인덱스는 데이터를 넣은 뒤 load.py 가 만든다 (INDEXES 아래 블록)

CREATE SCHEMA IF NOT EXISTS gold;

DROP TABLE IF EXISTS gold.drug_contraindication, gold.drug_dur_caution, gold.drug, gold.health_food, gold.load_info;

-- 의약품 제품 1개 = 1행 (판매 + 판매중지)
CREATE TABLE gold.drug (
    item_seq            text PRIMARY KEY,               -- 품목기준코드
    item_name           text NOT NULL,
    item_eng_name       text,
    entp_name           text,                           -- 업체
    sale_status         text NOT NULL CHECK (sale_status IN ('판매', '판매중지')),
    etc_otc_name        text,                           -- 전문의약품 / 일반의약품
    class_code          text,                           -- 분류 코드 (예: 01140)
    class_name          text,                           -- 분류 이름 (예: 해열.진통.소염제)
    atc_code            text,
    main_item_ingr      text,                           -- 주성분 원문
    chart               text,                           -- 성상 (모양·색 설명)
    image_url           text,
    item_permit_date    date,
    is_dur_target       boolean NOT NULL,               -- DUR 품목 마스터에 있음. false 면 병용금기 "판정 불가"
    -- e약은요 (일반인용 쉬운 설명, 일부 제품만)
    easy_efcy           text,
    easy_use_method     text,
    easy_atpn_warn      text,
    easy_atpn           text,
    easy_intrc          text,
    easy_se             text,
    easy_deposit_method text,
    -- 허가 문서 (전문가용 원문, 항목 제목과 본문을 줄바꿈으로 이음)
    doc_efficacy        text,                           -- 효능효과
    doc_dosage          text,                           -- 용법용량
    doc_precautions     text                            -- 사용상의 주의사항
);

-- 병용금기 제품쌍. A→B, B→A 양방향으로 들어 있다
CREATE TABLE gold.drug_contraindication (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_seq            text NOT NULL REFERENCES gold.drug,
    mixture_item_seq    text NOT NULL REFERENCES gold.drug,
    basis               text NOT NULL CHECK (basis IN ('품목 DUR', '성분 규칙')),  -- 품목 DUR = 금기, 성분 규칙 = 성분 기준 주의
    source_key          text NOT NULL,                  -- 품목 DUR: silver row_key / 성분 규칙: silver rule_key
    ingr_code           text,                           -- item_seq 쪽 DUR 성분 코드 (D코드)
    ingr_names          text[],
    mixture_ingr_code   text,
    mixture_ingr_names  text[],
    prohbt_content      text,                           -- 금기 내용
    remark              text,
    notification_date   date                            -- 고시일
);

-- DUR 주의. 한 행 = 제품 × 품목 규칙 × 연결된 성분 규칙
CREATE TABLE gold.drug_dur_caution (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_seq            text NOT NULL REFERENCES gold.drug,
    caution_type        text NOT NULL CHECK (caution_type IN
                            ('임부금기', '노인주의', '특정연령대금기', '용량주의', '투여기간주의', '효능군중복', '서방정분할주의')),
    ingr_code           text,
    ingr_name           text,
    mix_type            text,                           -- 단일 / 복합
    mix_ingr            text,
    form_name           text,                           -- 제형
    prohbt_content      text,
    remark              text,
    notification_date   date,
    link_status         text,                           -- 확정 / 조건별 복수 (조건별 복수는 하나를 골라 안내하지 말 것)
    -- 연결된 성분 규칙의 유형별 값
    grade               text,                           -- 임부금기 등급
    age_base            text,                           -- 특정연령대금기 기준 (예: 12세 미만)
    max_qty             text,                           -- 용량주의 1일 최대용량
    max_dosage_term     text,                           -- 투여기간주의 최대 투여기간
    effect_name         text,                           -- 효능군중복 효능군
    sers_name           text,                           -- 효능군중복 계열. 조합한 약끼리 같으면 효능군중복
    rule_prohbt_content text,
    rule_remark         text
);

-- 건강기능식품 1개 = 1행 (식품안전나라 C003)
CREATE TABLE gold.health_food (
    prdlst_report_no    text PRIMARY KEY,               -- 품목제조번호
    prdlst_nm           text NOT NULL,                  -- 제품명
    bssh_nm             text,                           -- 업체
    permit_date         date,                           -- 신고일
    prdt_shap_cd_nm     text,                           -- 제형 (정, 캡슐, 분말 등)
    dispos              text,                           -- 성상 (모양·색 설명)
    primary_fnclty      text,                           -- 주된 기능성
    ntk_mthd            text,                           -- 섭취 방법
    iftkn_atnt_matr_cn  text,                           -- 섭취 시 주의사항
    rawmtrl_nm          text,                           -- 원재료
    cstdy_mthd          text,                           -- 보관 방법
    pog_daycnt          text                            -- 유통기한
);

-- 적재 기록 (마지막 적재 1행)
CREATE TABLE gold.load_info (
    silver_snapshot     date NOT NULL,
    spec_version        text NOT NULL,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    row_counts          jsonb NOT NULL
);

-- INDEXES
CREATE INDEX drug_item_name_idx ON gold.drug (item_name);
CREATE INDEX drug_contraindication_pair_idx ON gold.drug_contraindication (item_seq, mixture_item_seq);
CREATE INDEX drug_dur_caution_item_idx ON gold.drug_dur_caution (item_seq, caution_type);
CREATE INDEX health_food_name_idx ON gold.health_food (prdlst_nm);

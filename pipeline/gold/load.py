"""Silver → Gold 적재 (명세: docs/gold_table_spec.md, 테이블 정의: schema.sql).

silver/_latest.json 의 스냅샷을 읽어 gold 테이블을 만들고, 트랜잭션 하나 안에서 기존 gold 테이블을 지우고 다시 넣는다.
중간에 실패하면 전부 되돌려 기존 gold 가 그대로 남는다.

  python pipeline/gold/load.py --check                      # DB 없이 gold 데이터 생성·검증만
  python pipeline/gold/load.py --host localhost             # SSM 터널로 RDS 에 적재 (접속 정보: Secrets Manager)
  python pipeline/gold/load.py                              # EC2 에서 RDS 에 직접 적재
  python pipeline/gold/load.py --dsn postgresql://...       # 다른 DB (로컬 테스트 등)

RDS 접속 정보는 Secrets Manager `pill-check/dev/app` 의 DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "s3"
SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
APP_SECRET = "pill-check/dev/app"
REGION = "us-east-1"

ITEM_LEVEL = "품목 DUR"
RULE_LEVEL = "성분 규칙"

# silver drug_product 의 DUR 주의 컬럼 → caution_type, 연결된 성분 규칙에서 가져올 값
CAUTION_COLUMNS = {
    "dur_pregnancy": "임부금기",
    "dur_elderly": "노인주의",
    "dur_age": "특정연령대금기",
    "dur_dosage": "용량주의",
    "dur_duration": "투여기간주의",
    "dur_efficacy_dup": "효능군중복",
}
RULE_VALUE_FIELDS = ["grade", "age_base", "max_qty", "max_dosage_term"]

# 테이블별 (컬럼, COPY 타입). 순서 = schema.sql 컬럼 순서 (id 제외)
DRUG_COLUMNS = [
    ("item_seq", "text"), ("item_name", "text"), ("item_eng_name", "text"), ("entp_name", "text"),
    ("sale_status", "text"), ("etc_otc_name", "text"), ("class_code", "text"), ("class_name", "text"),
    ("atc_code", "text"), ("main_item_ingr", "text"), ("chart", "text"), ("image_url", "text"),
    ("item_permit_date", "date"), ("is_dur_target", "bool"),
    ("easy_efcy", "text"), ("easy_use_method", "text"), ("easy_atpn_warn", "text"), ("easy_atpn", "text"),
    ("easy_intrc", "text"), ("easy_se", "text"), ("easy_deposit_method", "text"),
    ("doc_efficacy", "text"), ("doc_dosage", "text"), ("doc_precautions", "text"),
]
CONTRAINDICATION_COLUMNS = [
    ("item_seq", "text"), ("mixture_item_seq", "text"), ("basis", "text"), ("source_key", "text"),
    ("ingr_code", "text"), ("ingr_names", "text[]"), ("mixture_ingr_code", "text"), ("mixture_ingr_names", "text[]"),
    ("prohbt_content", "text"), ("remark", "text"), ("notification_date", "date"),
]
DUR_CAUTION_COLUMNS = [
    ("item_seq", "text"), ("caution_type", "text"), ("ingr_code", "text"), ("ingr_name", "text"),
    ("mix_type", "text"), ("mix_ingr", "text"), ("form_name", "text"), ("prohbt_content", "text"),
    ("remark", "text"), ("notification_date", "date"), ("link_status", "text"),
    ("grade", "text"), ("age_base", "text"), ("max_qty", "text"), ("max_dosage_term", "text"),
    ("effect_name", "text"), ("sers_name", "text"), ("rule_prohbt_content", "text"), ("rule_remark", "text"),
]
HEALTH_FOOD_COLUMNS = [
    ("prdlst_report_no", "text"), ("prdlst_nm", "text"), ("bssh_nm", "text"), ("permit_date", "date"),
    ("prdt_shap_cd_nm", "text"), ("dispos", "text"), ("primary_fnclty", "text"), ("ntk_mthd", "text"),
    ("iftkn_atnt_matr_cn", "text"), ("rawmtrl_nm", "text"), ("cstdy_mthd", "text"), ("pog_daycnt", "text"),
]
TABLES = {
    "drug": DRUG_COLUMNS,
    "drug_contraindication": CONTRAINDICATION_COLUMNS,
    "drug_dur_caution": DUR_CAUTION_COLUMNS,
    "health_food": HEALTH_FOOD_COLUMNS,
}

TEST_HEALTH_FOOD_BUSINESS = "식약처TEST업소"  # 식약처 시험용 데이터


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def read_silver(root, table, snapshot, columns=None):
    path = Path(root) / "silver" / table / f"snapshot={snapshot}" / "data.parquet"
    return pq.read_table(path, columns=columns).to_pylist()


def document_text(articles):
    """허가 문서 항목 목록 → 글 하나. 섹션 제목은 바뀔 때만, 항목 제목과 본문은 줄바꿈으로 잇는다."""
    if not articles:
        return None
    lines, section = [], None
    for article in articles:
        if article["section_title"] and article["section_title"] != section:
            section = article["section_title"]
            lines.append(section)
        lines += [text for text in (article["article_title"], article["text"]) if text]
    return "\n".join(lines) or None


def split_class(prduct_type):
    """'[01140]해열.진통.소염제' → ('01140', '해열.진통.소염제')"""
    if not prduct_type:
        return None, None
    match = re.match(r"\[(\w+)\](.*)", prduct_type)
    return (match.group(1), match.group(2).strip() or None) if match else (None, prduct_type)


def first_image(product):
    if product["big_prdt_img_url"]:
        return product["big_prdt_img_url"]
    for pill in product["pills"] or []:
        if pill["item_image"]:
            return pill["item_image"]
    return None


def build_drug(products):
    rows = []
    for p in products:
        class_code, class_name = split_class(p["prduct_type"])
        easy = p["easy_info"] or {}
        rows.append({
            "item_seq": p["item_seq"], "item_name": p["item_name"], "item_eng_name": p["item_eng_name"],
            "entp_name": p["entp_name"], "sale_status": p["sale_status"], "etc_otc_name": p["etc_otc_name"],
            "class_code": class_code, "class_name": class_name, "atc_code": p["atc_code"],
            "main_item_ingr": p["main_item_ingr"], "chart": p["chart"], "image_url": first_image(p),
            "item_permit_date": p["item_permit_date"], "is_dur_target": p["dur_info"] is not None,
            "easy_efcy": easy.get("efcy"), "easy_use_method": easy.get("use_method"),
            "easy_atpn_warn": easy.get("atpn_warn"), "easy_atpn": easy.get("atpn"), "easy_intrc": easy.get("intrc"),
            "easy_se": easy.get("se"), "easy_deposit_method": easy.get("deposit_method"),
            "doc_efficacy": document_text(p["doc_efficacy"]), "doc_dosage": document_text(p["doc_dosage"]),
            "doc_precautions": document_text(p["doc_precautions"]),
        })
    return rows


def product_mcodes(product):
    """제품의 원료 M코드. 원료 성분이 없으면 허가 주성분 코드로 보완."""
    if product["ingredients"]:
        return {i["mtral_code"] for i in product["ingredients"] if i["mtral_code"]}
    return set(product["main_item_ingr_codes"] or [])


def build_contraindication(contraindications, products):
    """품목표 제품쌍 + 품목표에 한 번도 반영되지 않은 성분 규칙으로 만든 제품쌍.

    품목표에 반영된 규칙은 식약처가 제형 등 조건을 따져 제품에 적용한 결과라 그대로 따른다 (예: 케토코나졸 × 트리아졸람은
    정제만 적용, 크림 제외). API 품목표에는 공식 DUR 에 있는 규칙이 통째로 빠진 경우가 있어 (예: 로수바스타틴 × 사이클로스포린,
    2026-10-16 의약품안전나라에서 확인) 그런 규칙만 성분으로 펼친다. 배경: docs/gold_table_spec.md
    """
    item_rows = [r for r in contraindications if r["level"] == "품목"]
    rules = [r for r in contraindications if r["level"] == "성분" and r["is_rule_valid"]]
    reflected_rules = {(r["ingr_code"], r["mixture_ingr_code"]) for r in item_rows}

    rows = [{
        "item_seq": r["item_seq"], "mixture_item_seq": r["mixture_item_seq"], "basis": ITEM_LEVEL,
        "source_key": r["row_key"], "ingr_code": r["ingr_code"], "ingr_names": r["ingr_names"],
        "mixture_ingr_code": r["mixture_ingr_code"], "mixture_ingr_names": r["mixture_ingr_names"],
        "prohbt_content": r["prohbt_content"], "remark": r["remark"], "notification_date": r["notification_date"],
    } for r in item_rows]
    item_pairs = {(r["item_seq"], r["mixture_item_seq"]) for r in item_rows}

    # M코드 → D코드: 단일 성분 규칙의 원료 코드만 (복합제 규칙의 ori_codes 에는 상대 성분 M코드가 섞여 있다)
    m_to_d = {}
    for r in rules:
        if r["mix_type"] == "단일":
            for m in r["ori_codes"] or []:
                m_to_d.setdefault(m, set()).add(r["ingr_code"])
        if r["mixture_mix_type"] == "단일":
            for m in r["mixture_ori_codes"] or []:
                m_to_d.setdefault(m, set()).add(r["mixture_ingr_code"])
    products_by_d = {}
    for p in products:
        for m in product_mcodes(p):
            for d in m_to_d.get(m, ()):
                products_by_d.setdefault(d, set()).add(p["item_seq"])

    # 양쪽 모두 단일 성분인 미반영 규칙만 제품에 적용 (복합 조합 규칙은 제품 성분 구성으로 정확히 맞출 수 없음)
    seen = set()
    for r in rules:
        if r["mix_type"] != "단일" or r["mixture_mix_type"] != "단일":
            continue
        if (r["ingr_code"], r["mixture_ingr_code"]) in reflected_rules:
            continue
        for x in products_by_d.get(r["ingr_code"], ()):
            for y in products_by_d.get(r["mixture_ingr_code"], ()):
                if x == y or (x, y) in item_pairs:
                    continue
                for a, b, a_side, b_side in ((x, y, "", "mixture_"), (y, x, "mixture_", "")):
                    key = (a, b, r[f"{a_side}ingr_code"], r[f"{b_side}ingr_code"], r["prohbt_content"], r["remark"])
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "item_seq": a, "mixture_item_seq": b, "basis": RULE_LEVEL, "source_key": r["rule_key"],
                        "ingr_code": r[f"{a_side}ingr_code"], "ingr_names": r[f"{a_side}ingr_names"],
                        "mixture_ingr_code": r[f"{b_side}ingr_code"], "mixture_ingr_names": r[f"{b_side}ingr_names"],
                        "prohbt_content": r["prohbt_content"], "remark": r["remark"],
                        "notification_date": r["notification_date"],
                    })
    return rows


def build_dur_caution(products):
    rows = []
    for p in products:
        for column, caution_type in CAUTION_COLUMNS.items():
            for item in p[column] or []:
                ingr_name = item.get("ingr_name") or ", ".join(item.get("ingr_names") or []) or None
                base = {
                    "item_seq": p["item_seq"], "caution_type": caution_type, "ingr_code": item["ingr_code"],
                    "ingr_name": ingr_name, "mix_type": item["mix_type"], "mix_ingr": item["mix_ingr"],
                    "form_name": item["form_name"], "prohbt_content": item["prohbt_content"], "remark": item["remark"],
                    "notification_date": item["notification_date"], "link_status": item["link_status"],
                    "effect_name": item.get("effect_name"), "sers_name": item.get("sers_name"),
                }
                for rule in item["ingredient_rules"] or [{}]:
                    row = dict(base, rule_prohbt_content=rule.get("prohbt_content"), rule_remark=rule.get("remark"))
                    for field in RULE_VALUE_FIELDS:
                        row[field] = rule.get(field)
                    rows.append(row)
        split = p["dur_sr_split"]
        if split:
            rows.append({
                "item_seq": p["item_seq"], "caution_type": "서방정분할주의", "mix_type": split["mix_type"],
                "form_name": split["form_code_name"], "prohbt_content": split["prohbt_content"],
                "remark": split["remark"],
            })
    return rows


def build_health_food(foods):
    names = [name for name, _ in HEALTH_FOOD_COLUMNS]
    return [{name: f[name] for name in names} for f in foods
            if not (f["bssh_nm"] or "").startswith(TEST_HEALTH_FOOD_BUSINESS)]


def build(root):
    latest = json.loads((Path(root) / "silver" / "_latest.json").read_text(encoding="utf-8"))
    snapshots = latest["tables"]
    log(f"silver 스냅샷 {snapshots}")

    products = read_silver(root, "drug_product", snapshots["drug_product"], columns=[
        "item_seq", "item_name", "item_eng_name", "entp_name", "sale_status", "etc_otc_name", "prduct_type",
        "atc_code", "main_item_ingr", "main_item_ingr_codes", "chart", "big_prdt_img_url", "pills",
        "item_permit_date", "dur_info", "easy_info", "ingredients", "doc_efficacy", "doc_dosage", "doc_precautions",
        "dur_sr_split", *CAUTION_COLUMNS,
    ])
    contraindications = read_silver(root, "dur_contraindication", snapshots["dur_contraindication"])
    foods = read_silver(root, "health_food_product", snapshots["health_food_product"])

    data = {
        "drug": build_drug(products),
        "drug_contraindication": build_contraindication(contraindications, products),
        "drug_dur_caution": build_dur_caution(products),
        "health_food": build_health_food(foods),
    }
    expected_item_rows = sum(1 for r in contraindications if r["level"] == "품목")
    return latest, data, expected_item_rows


def validate(data, expected_item_rows):
    """적재 전 검증. 문제 목록을 돌려준다 (비어 있으면 통과)."""
    problems = []
    for table, key in (("drug", "item_seq"), ("health_food", "prdlst_report_no")):
        keys = [r[key] for r in data[table]]
        if None in keys or len(keys) != len(set(keys)):
            problems.append(f"{table}: PK {key} 에 null 또는 중복")
    drugs = {r["item_seq"] for r in data["drug"]}
    for table, columns in (("drug_contraindication", ("item_seq", "mixture_item_seq")),
                           ("drug_dur_caution", ("item_seq",))):
        missing = {r[c] for r in data[table] for c in columns} - drugs
        if missing:
            problems.append(f"{table}: drug 에 없는 제품 {len(missing)}개 (예: {sorted(missing)[:5]})")
    item_rows = sum(1 for r in data["drug_contraindication"] if r["basis"] == ITEM_LEVEL)
    if item_rows != expected_item_rows:
        problems.append(f"drug_contraindication: 품목 DUR {item_rows:,}행 != silver 품목 {expected_item_rows:,}행")
    directed = {(r["item_seq"], r["mixture_item_seq"]) for r in data["drug_contraindication"]}
    one_way = sum(1 for a, b in directed if (b, a) not in directed)
    if one_way:
        problems.append(f"drug_contraindication: 반대 방향이 없는 쌍 {one_way:,}개")
    return problems


def connection_info(host_override):
    import boto3

    secret = json.loads(boto3.client("secretsmanager", region_name=REGION)
                        .get_secret_value(SecretId=APP_SECRET)["SecretString"])
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USERNAME", "DB_PASSWORD") if not secret.get(k)]
    if missing:
        sys.exit(f"Secrets Manager {APP_SECRET} 에 값이 없음: {missing}")
    return {
        "host": host_override or secret["DB_HOST"], "port": int(secret.get("DB_PORT") or 5432),
        "dbname": secret["DB_NAME"], "user": secret["DB_USERNAME"], "password": secret["DB_PASSWORD"],
        "sslmode": "require",
    }


def load(conninfo, latest, data):
    import psycopg

    schema_sql, index_sql = SCHEMA_SQL.read_text(encoding="utf-8").split("-- INDEXES")
    connect = psycopg.connect(conninfo) if isinstance(conninfo, str) else psycopg.connect(**conninfo)
    with connect as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(schema_sql)
            for table, columns in TABLES.items():
                names = [name for name, _ in columns]
                with cur.copy(f"COPY gold.{table} ({', '.join(names)}) FROM STDIN") as copy:
                    copy.set_types([type_ for _, type_ in columns])
                    for row in data[table]:
                        copy.write_row([row.get(name) for name in names])
                log(f"  gold.{table} {len(data[table]):,}행")
            cur.execute(index_sql)
            counts = {}
            for table in TABLES:
                cur.execute(f"SELECT count(*) FROM gold.{table}")
                counts[table] = cur.fetchone()[0]
            wrong = {t: (counts[t], len(data[t])) for t in TABLES if counts[t] != len(data[t])}
            if wrong:
                raise RuntimeError(f"적재 행 수 불일치 (DB, 생성): {wrong}")
            cur.execute("INSERT INTO gold.load_info (silver_snapshot, spec_version, row_counts) VALUES (%s, %s, %s)",
                        (latest["snapshot"], latest["spec_version"], json.dumps(counts)))
    return counts


def main():
    parser = argparse.ArgumentParser(description="silver → gold 적재")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--check", action="store_true", help="DB 없이 gold 데이터 생성·검증만")
    parser.add_argument("--host", help="DB 호스트 덮어쓰기 (SSM 터널이면 localhost)")
    parser.add_argument("--dsn", help="Secrets Manager 대신 이 접속 문자열 사용")
    args = parser.parse_args()

    log("1/3 silver → gold 데이터 생성")
    latest, data, expected_item_rows = build(args.root)
    for table, rows in data.items():
        log(f"  {table} {len(rows):,}행")
    basis = Counter(r["basis"] for r in data["drug_contraindication"])
    log(f"  병용금기 근거별 {dict(basis)}")

    log("2/3 검증")
    problems = validate(data, expected_item_rows)
    if problems:
        for problem in problems:
            log(f"  실패: {problem}")
        sys.exit(1)
    log("  통과")
    if args.check:
        return

    log("3/3 적재 (실패하면 기존 gold 유지)")
    counts = load(args.dsn or connection_info(args.host), latest, data)
    log(f"완료 {counts}")


if __name__ == "__main__":
    main()

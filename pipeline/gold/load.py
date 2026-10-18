"""Silver → Gold 적재 (명세: docs/gold_table_spec.md, 테이블 정의: schema.sql).

silver/_latest.json 의 스냅샷을 읽어 트랜잭션 하나 안에서 gold 테이블을 지우고 다시 만든다.
메모리를 아끼려고 테이블 하나씩, silver 를 BATCH_ROWS 행 단위로 읽어 바로 DB 로 보낸다.
검증은 DB 제약(PK, FK, CHECK)과 적재 후 SQL 확인으로 하며, 하나라도 실패하면 전부 되돌려 기존 gold 가 그대로 남는다.

  python pipeline/gold/load.py --host localhost             # SSM 터널로 RDS 에 적재 (접속 정보: Secrets Manager)
  python pipeline/gold/load.py                              # EC2 에서 RDS 에 직접 적재
  python pipeline/gold/load.py --dsn postgresql://...       # 다른 DB (로컬 테스트 등)
  python pipeline/gold/load.py --force                      # 이미 적재한 silver 여도 다시 적재 (코드·스키마를 바꿨을 때)

이미 적재한 silver(_latest.json 의 written_at 이 gold.load_info 와 같음)면 아무것도 하지 않고 끝난다.
종료 코드: 0 = 적재 또는 건너뜀, 1 = 실패 (기존 gold 유지), 2 = DB 접속 실패 (RDS 가 꺼져 있거나 터널·접속 정보 확인)

RDS 접속 정보는 Secrets Manager `pill-check/dev/app` 의 DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD.
"""

import argparse
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "s3"
SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
APP_SECRET = "pill-check/dev/app"
REGION = "us-east-1"
CONNECT_TIMEOUT_SECONDS = 15
BATCH_ROWS = 1000        # silver 를 읽는 단위 (허가 문서가 커서 작게)
CSV_BATCH_ROWS = 50000   # 열 단위 CSV 로 보내는 단위

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
    ("item_permit_date", "date"),
    ("easy_efcy", "text"), ("easy_use_method", "text"), ("easy_atpn_warn", "text"), ("easy_atpn", "text"),
    ("easy_intrc", "text"), ("easy_se", "text"), ("easy_deposit_method", "text"),
    ("doc_efficacy", "text"), ("doc_dosage", "text"), ("doc_precautions", "text"),
]
CONTRAINDICATION_COLUMNS = [
    ("item_seq", "text"), ("mixture_item_seq", "text"), ("basis", "text"), ("source_key", "text"),
    ("ingr_code", "text"), ("ingr_names", "text[]"), ("mixture_ingr_code", "text"), ("mixture_ingr_names", "text[]"),
    ("prohbt_content", "text"), ("remark", "text"), ("notification_date", "date"), ("carried_from", "date"),
]
DRUG_INGREDIENT_COLUMNS = [("item_seq", "text"), ("ingr_key", "text"), ("ingr_name", "text"), ("dur_ingr_code", "text")]
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
TABLES = ["drug", "drug_contraindication", "drug_dur_caution", "drug_ingredient", "health_food"]

DRUG_SOURCE_COLUMNS = [
    "item_seq", "item_name", "item_eng_name", "entp_name", "sale_status", "etc_otc_name", "prduct_type",
    "atc_code", "main_item_ingr", "chart", "big_prdt_img_url", "pills", "item_permit_date", "easy_info",
    "doc_efficacy", "doc_dosage", "doc_precautions",
]
RULE_COLUMNS = [  # 성분 규칙에서 쓰는 컬럼
    "rule_key", "ingr_code", "ingr_names", "mix_type", "ori_codes", "mixture_ingr_code", "mixture_ingr_names",
    "mixture_mix_type", "mixture_ori_codes", "prohbt_content", "remark", "notification_date",
]
ITEM_SOURCE_COLUMNS = [
    "item_seq", "mixture_item_seq", "row_key", "ingr_code", "ingr_names", "mixture_ingr_code",
    "mixture_ingr_names", "prohbt_content", "remark", "notification_date",
]

TEST_HEALTH_FOOD_BUSINESS = "식약처TEST업소"  # 식약처 시험용 데이터
CARRY_OVER_SNAPSHOTS = 3  # 품목표에서 빠진 판매 제품을 찾아볼 이전 수집 수
FORM_SUFFIXES = ("제피세립", "세립", "과립", "미분화")  # 같은 성분의 원료 이름 뒤에 붙는 제형 표현

# 공식 DUR(의약품안전나라)로 확인한 사례. 두 제품이 모두 있을 때만 확인한다 (제품이 빠지는 스냅샷도 있으므로)
OFFICIAL_CASES = [
    ("198902794", "199101243", ITEM_LEVEL),  # 트리람정 × 더마졸정: 품목표 금기
    ("201603999", "199604696", RULE_LEVEL),  # 뉴로스틴정 × 산디문: API 품목표에서 빠진 규칙 (로수바스타틴 × 사이클로스포린)
    ("198902794", "199301086", None),        # 트리람정 × 케토코나졸 크림: 공식 DUR 도 제외 (정제만 적용)
]


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def silver_path(root, table, snapshot):
    return Path(root) / "silver" / table / f"snapshot={snapshot}" / "data.parquet"


def iter_batches(path, columns):
    """silver 를 BATCH_ROWS 행씩 dict 목록으로 읽는다."""
    for batch in pq.ParquetFile(path).iter_batches(batch_size=BATCH_ROWS, columns=columns):
        yield batch.to_pylist()


# ---------------------------------------------------------------- 변환

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


def drug_row(p):
    class_code, class_name = split_class(p["prduct_type"])
    easy = p["easy_info"] or {}
    return {
        "item_seq": p["item_seq"], "item_name": p["item_name"], "item_eng_name": p["item_eng_name"],
        "entp_name": p["entp_name"], "sale_status": p["sale_status"], "etc_otc_name": p["etc_otc_name"],
        "class_code": class_code, "class_name": class_name, "atc_code": p["atc_code"],
        "main_item_ingr": p["main_item_ingr"], "chart": p["chart"], "image_url": first_image(p),
        "item_permit_date": p["item_permit_date"],
        "easy_efcy": easy.get("efcy"), "easy_use_method": easy.get("use_method"),
        "easy_atpn_warn": easy.get("atpn_warn"), "easy_atpn": easy.get("atpn"), "easy_intrc": easy.get("intrc"),
        "easy_se": easy.get("se"), "easy_deposit_method": easy.get("deposit_method"),
        "doc_efficacy": document_text(p["doc_efficacy"]), "doc_dosage": document_text(p["doc_dosage"]),
        "doc_precautions": document_text(p["doc_precautions"]),
    }


def iter_drug_rows(root, snapshot):
    for batch in iter_batches(silver_path(root, "drug_product", snapshot), DRUG_SOURCE_COLUMNS):
        yield from (drug_row(p) for p in batch)


def dur_caution_rows(p):
    rows = []
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
            "form_name": split["form_code_name"], "prohbt_content": split["prohbt_content"], "remark": split["remark"],
        })
    return rows


def iter_dur_caution_rows(root, snapshot):
    columns = ["item_seq", "dur_sr_split", *CAUTION_COLUMNS]
    for batch in iter_batches(silver_path(root, "drug_product", snapshot), columns):
        for p in batch:
            yield from dur_caution_rows(p)


def pg_text_array(column):
    """list<string> 열 → PostgreSQL 배열 리터럴 문자열 열 ('{"a","b"}'). null 목록은 null."""
    lists = column.combine_chunks() if isinstance(column, pa.ChunkedArray) else column
    escaped = pc.replace_substring(pc.replace_substring(lists.values, "\\", "\\\\"), '"', '\\"')
    quoted = pc.binary_join_element_wise('"', escaped, '"', "")
    joined = pc.binary_join(pa.ListArray.from_arrays(lists.offsets, quoted, mask=lists.is_null()), ",")
    return pc.binary_join_element_wise("{", joined, "}", "")


def previous_snapshots(root, table, snapshot):
    """snapshot 보다 이전 silver 스냅샷 날짜, 최신순."""
    found = [p.name.removeprefix("snapshot=") for p in (Path(root) / "silver" / table).glob("snapshot=*")
             if (p / "data.parquet").exists()]
    return sorted((s for s in found if s < snapshot), reverse=True)


def read_item_rows(root, snapshot):
    return pq.read_table(silver_path(root, "dur_contraindication", snapshot), columns=ITEM_SOURCE_COLUMNS,
                         filters=[("level", "=", "품목")])


def item_level_rows(root, snapshot, drug_items, sale_items):
    """이번 품목표 + 이번에 통째로 빠진 판매 제품의 이전 품목표 행. (행, 유지 내역, 제외 내역)을 돌려준다.

    drug(silver drug_product)에 없는 제품이 낀 행은 뺀다. API 마다 받는 시각이 달라 품목표에만 먼저 들어온 신제품
    (2026-10-16 재수집: 10-13 허가 제품 1개, 72행)이나 취하된 제품이 있을 수 있다. 뺀 내역은 gold.load_info.excluded 에 남긴다.

    API 품목표는 수집할 때마다 제품이 통째로 빠졌다 들어오는 일이 있다 (2026-10-16 재수집에서 판매 제품 580개, 4,236행이 빠짐.
    의약품안전나라에는 그대로 있음). 빠진 판매 제품은 이전 수집(최대 CARRY_OVER_SNAPSHOTS 개)에서 가장 최근 행을 유지하고
    carried_from 에 그 날짜를 남긴다. 무엇을 유지했는지는 gold.load_info.carried_over 에 기록한다.
    """
    current = read_item_rows(root, snapshot)
    drug_array = pa.array(sorted(drug_items), pa.string())
    known = pc.and_(pc.is_in(current["item_seq"], drug_array), pc.is_in(current["mixture_item_seq"], drug_array))
    unknown = current.filter(pc.invert(known))
    excluded = {"rows": unknown.num_rows, "item_seqs": sorted(
        set(unknown["item_seq"].to_pylist() + unknown["mixture_item_seq"].to_pylist()) - drug_items)}
    current = current.filter(known)
    current = current.append_column("carried_from", pa.nulls(current.num_rows, pa.date32()))
    present = set(pc.unique(current["item_seq"]).to_pylist())
    known_keys = set(current["row_key"].to_pylist())
    sale_array = pa.array(sorted(sale_items), pa.string())
    handled, carried, report = set(), [], {}
    for previous in previous_snapshots(root, "dur_contraindication", snapshot)[:CARRY_OVER_SNAPSHOTS]:
        old = read_item_rows(root, previous)
        vanished = (set(pc.unique(old["item_seq"]).to_pylist()) - present - handled) & sale_items
        if not vanished:
            continue
        vanished_array = pa.array(sorted(vanished), pa.string())
        touches = pc.or_(pc.is_in(old["item_seq"], vanished_array), pc.is_in(old["mixture_item_seq"], vanished_array))
        both_on_sale = pc.and_(pc.is_in(old["item_seq"], sale_array), pc.is_in(old["mixture_item_seq"], sale_array))
        rows = old.filter(pc.and_(touches, both_on_sale))
        rows = rows.filter(pc.invert(pc.is_in(rows["row_key"], pa.array(sorted(known_keys), pa.string()))))
        known_keys |= set(rows["row_key"].to_pylist())
        handled |= vanished
        carried.append(rows.append_column(
            "carried_from", pa.array([date.fromisoformat(previous)] * rows.num_rows, pa.date32())))
        report[previous] = {"products": len(vanished), "rows": rows.num_rows, "item_seqs": sorted(vanished)}
    return pa.concat_tables([current, *carried]), report, excluded


def item_contraindication_table(items):
    """품목표 행 → gold 컬럼 순서의 arrow 테이블 (파이썬 객체를 거치지 않는다)."""
    return pa.table({
        "item_seq": items["item_seq"], "mixture_item_seq": items["mixture_item_seq"],
        "basis": pa.array([ITEM_LEVEL] * items.num_rows, pa.string()), "source_key": items["row_key"],
        "ingr_code": items["ingr_code"], "ingr_names": pg_text_array(items["ingr_names"]),
        "mixture_ingr_code": items["mixture_ingr_code"], "mixture_ingr_names": pg_text_array(items["mixture_ingr_names"]),
        "prohbt_content": items["prohbt_content"], "remark": items["remark"],
        "notification_date": items["notification_date"], "carried_from": items["carried_from"],
    })


def product_mcodes(product):
    """제품의 원료 M코드. 원료 성분이 없으면 허가 주성분 코드로 보완."""
    if product["ingredients"]:
        return {i["mtral_code"] for i in product["ingredients"] if i["mtral_code"]}
    return set(product["main_item_ingr_codes"] or [])


def read_valid_rules(root, snapshot):
    """유효한 성분 병용금기 규칙 (파일 순서). 80만 행 파일을 통째로 읽고 거르면 1GB 넘게 써서, 필요한 열만 조각 단위로 거른다."""
    rules = []
    for batch in pq.ParquetFile(silver_path(root, "dur_contraindication", snapshot)).iter_batches(
            batch_size=CSV_BATCH_ROWS, columns=["level", "is_rule_valid", *RULE_COLUMNS]):
        valid = pc.and_(pc.equal(batch["level"], "성분"), pc.fill_null(batch["is_rule_valid"], False))
        rules += pa.Table.from_batches([batch]).filter(valid).select(RULE_COLUMNS).to_pylist()
    return rules


def rule_m_to_d(rules):
    """M코드 → D코드: 단일 성분 쪽의 원료 코드만 (복합제 쪽 ori_codes 는 조합 성분 M코드 묶음이라 1:1 대응이 아니다)."""
    m_to_d = {}
    for r in rules:
        for side in ("", "mixture_"):
            if r[f"{side}mix_type"] == "단일":
                for m in r[f"{side}ori_codes"] or []:
                    m_to_d.setdefault(m, set()).add(r[f"{side}ingr_code"])
    return m_to_d


def iter_rule_contraindication_rows(root, snapshot, product_snapshot, items):
    """성분 규칙을 제품쌍으로 펼친다 (품목표에 이미 있는 제품쌍은 제외).

    - 품목표에 한 번도 반영되지 않은 규칙: 모든 제품에 펼친다. API 품목표에는 공식 DUR 에 있는 규칙이 통째로 빠진 경우가 있다
      (예: 로수바스타틴 × 사이클로스포린, 2026-10-16 의약품안전나라에서 확인)
    - 품목표에 반영된 규칙: 식약처가 제형 등 조건을 따져 제품에 적용한 결과라 그대로 따른다 (예: 케토코나졸 × 트리아졸람은
      정제만, 크림 제외). 단 품목표에 아예 없는 제품 중 품목표 마지막 고시일 이후 허가된 신제품에는 펼친다 (반영 전일 수 있음)
    - 단일 성분 쪽은 D코드로, 복합제 쪽은 규칙의 원료 코드(ori_codes)를 모두 가진 제품으로 맞춘다 (예: 팍스로비드 =
      니르마트렐비르 + 리토나비르)
    배경: docs/gold_table_spec.md
    """
    rules = read_valid_rules(root, snapshot)
    reflected = items.group_by(["ingr_code", "mixture_ingr_code"]).aggregate([])  # 행 순서가 매번 다르므로 한 번만
    reflected_rules = set(zip(reflected["ingr_code"].to_pylist(), reflected["mixture_ingr_code"].to_pylist()))
    in_item_table = set(pc.unique(items["item_seq"]).to_pylist())
    last_notified = pc.max(items["notification_date"]).as_py()

    m_to_d = rule_m_to_d(rules)
    products_by_d, products_by_m, new_products = {}, {}, set()
    for batch in iter_batches(silver_path(root, "drug_product", product_snapshot),
                              ["item_seq", "ingredients", "main_item_ingr_codes", "item_permit_date"]):
        for p in batch:
            for m in product_mcodes(p):
                products_by_m.setdefault(m, set()).add(p["item_seq"])
                for d in m_to_d.get(m, ()):
                    products_by_d.setdefault(d, set()).add(p["item_seq"])
            permitted = p["item_permit_date"]
            if p["item_seq"] not in in_item_table and permitted and last_notified and permitted > last_notified:
                new_products.add(p["item_seq"])

    def side_products(rule, side):
        if rule[f"{side}mix_type"] == "단일":
            return products_by_d.get(rule[f"{side}ingr_code"], set())
        ori = rule[f"{side}ori_codes"] or []
        if not ori:
            return set()
        return set.intersection(*(products_by_m.get(m, set()) for m in ori))

    targets = []
    for r in rules:
        xs, ys = side_products(r, ""), side_products(r, "mixture_")
        if not (xs and ys):
            continue
        reflected_rule = (r["ingr_code"], r["mixture_ingr_code"]) in reflected_rules
        if reflected_rule and not (xs & new_products or ys & new_products):
            continue  # 반영된 규칙은 신제품이 낀 쌍만
        targets.append((r, xs, ys, reflected_rule))

    # 품목표에 이미 있는 제품쌍은 넣지 않는다. 펼칠 제품이 낀 쌍만 들고 있는다
    candidates = pa.array(sorted({s for _, xs, ys, _ in targets for s in xs | ys}), pa.string())
    pairs = items.select(["item_seq", "mixture_item_seq"])
    pairs = pairs.filter(pc.is_in(pairs["item_seq"], candidates))
    item_pairs = set(zip(pairs["item_seq"].to_pylist(), pairs["mixture_item_seq"].to_pylist()))

    seen = set()
    for r, xs, ys, new_only in targets:
        for x in xs:
            for y in ys:
                if x == y or (x, y) in item_pairs or (new_only and x not in new_products and y not in new_products):
                    continue
                for a, b, a_side, b_side in ((x, y, "", "mixture_"), (y, x, "mixture_", "")):
                    key = (a, b, r[f"{a_side}ingr_code"], r[f"{b_side}ingr_code"], r["prohbt_content"], r["remark"])
                    if key in seen:
                        continue
                    seen.add(key)
                    yield {
                        "item_seq": a, "mixture_item_seq": b, "basis": RULE_LEVEL, "source_key": r["rule_key"],
                        "ingr_code": r[f"{a_side}ingr_code"], "ingr_names": r[f"{a_side}ingr_names"],
                        "mixture_ingr_code": r[f"{b_side}ingr_code"], "mixture_ingr_names": r[f"{b_side}ingr_names"],
                        "prohbt_content": r["prohbt_content"], "remark": r["remark"],
                        "notification_date": r["notification_date"],
                    }


def base_ingredient_name(name):
    """원료 이름에서 괄호와 제형 표현을 떼어 같은 성분끼리 묶는다. '아세트아미노펜 과립(미분화)' → '아세트아미노펜'"""
    name = re.sub(r"\(.*?\)", "", name or "").replace(" ", "")
    for suffix in FORM_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            name = name[: -len(suffix)]
    return name or None


def parse_main_ingredients(text):
    """'[M040715]푸로세미드|[M088335]클로트리마졸' → {M코드: 이름}"""
    return dict(re.findall(r"\[(M\d+)\]([^|]+)", text or ""))


def iter_drug_ingredient_rows(root, snapshot, product_snapshot):
    """제품별 성분 (동일 성분 중복 판정용).

    같은 성분 키: DUR 성분 코드(D코드). 원료 코드(M코드)가 D코드로 매핑되지 않으면 정리한 원료 이름.
    매핑 출처: 성분 병용금기 규칙의 원료 코드 + 단일 성분 제품의 품목 병용금기·DUR 주의 (제품 M코드 1개 ↔ 규칙 D코드).
    아세트아미노펜처럼 원료 코드가 제형별로 여러 개인 성분은, 매핑된 원료와 정리한 이름이 같으면 같은 D코드로 본다.
    """
    rules = read_valid_rules(root, snapshot)
    m_to_d = rule_m_to_d(rules)
    d_names = {}
    for r in rules:
        for side in ("", "mixture_"):
            if r[f"{side}ingr_names"]:
                d_names.setdefault(r[f"{side}ingr_code"], r[f"{side}ingr_names"][0])

    columns = ["item_seq", "ingredients", "main_item_ingr", *CAUTION_COLUMNS]
    product_m = {}  # item_seq → {M코드: 원료 이름}
    for batch in iter_batches(silver_path(root, "drug_product", product_snapshot), columns):
        for p in batch:
            if p["ingredients"]:
                names = {i["mtral_code"]: i["mtral_nm"] for i in p["ingredients"] if i["mtral_code"]}
            else:
                names = parse_main_ingredients(p["main_item_ingr"])
            product_m[p["item_seq"]] = names
            if len(names) != 1:
                continue
            m = next(iter(names))
            for column in CAUTION_COLUMNS:
                for item in p[column] or []:
                    if item["mix_type"] == "단일" and item["ingr_code"]:
                        m_to_d.setdefault(m, set()).add(item["ingr_code"])
                        name = item.get("ingr_name") or (item.get("ingr_names") or [None])[0]
                        if name:
                            d_names.setdefault(item["ingr_code"], name)
    items = pq.read_table(silver_path(root, "dur_contraindication", snapshot),
                          columns=["item_seq", "mix_type", "ingr_code"], filters=[("level", "=", "품목")])
    single = items.filter(pc.equal(items["mix_type"], "단일")).group_by(["item_seq", "ingr_code"]).aggregate([])
    for item_seq, d in zip(single["item_seq"].to_pylist(), single["ingr_code"].to_pylist()):
        names = product_m.get(item_seq, {})
        if len(names) == 1:
            m_to_d.setdefault(next(iter(names)), set()).add(d)

    # 이름으로 보완: 매핑된 원료의 정리한 이름 → D코드
    all_names = {m: n for names in product_m.values() for m, n in names.items()}
    name_to_d = {}
    for m, ds in m_to_d.items():
        base = base_ingredient_name(all_names.get(m))
        if base:
            name_to_d.setdefault(base, set()).update(ds)

    for item_seq, names in product_m.items():
        keys = {}
        for m, name in names.items():
            base = base_ingredient_name(name)
            ds = m_to_d.get(m) or name_to_d.get(base) or set()
            for d in ds:
                keys[d] = {"ingr_name": d_names.get(d) or name, "dur_ingr_code": d}
            if not ds and base:
                keys.setdefault(base, {"ingr_name": name.strip(), "dur_ingr_code": None})
        for key, value in keys.items():
            yield {"item_seq": item_seq, "ingr_key": key, **value}


def health_food_table(root, snapshot):
    names = [name for name, _ in HEALTH_FOOD_COLUMNS]
    t = pq.read_table(silver_path(root, "health_food_product", snapshot), columns=names)
    is_test = pc.fill_null(pc.starts_with(t["bssh_nm"], TEST_HEALTH_FOOD_BUSINESS), False)
    return t.filter(pc.invert(is_test))


# ---------------------------------------------------------------- 적재

def copy_rows(cur, table, columns, rows):
    names = [name for name, _ in columns]
    count = 0
    with cur.copy(f"COPY gold.{table} ({', '.join(names)}) FROM STDIN") as copy:
        copy.set_types([type_ for _, type_ in columns])
        for row in rows:
            copy.write_row([row.get(name) for name in names])
            count += 1
    return count


def copy_arrow(cur, table, columns, data):
    """arrow 테이블을 CSV 로 바꿔 COPY. null 은 따옴표 없는 빈 값 = NULL (silver 에는 빈 문자열이 없다)."""
    names = [name for name, _ in columns]
    options = pacsv.WriteOptions(include_header=False)
    with cur.copy(f"COPY gold.{table} ({', '.join(names)}) FROM STDIN WITH (FORMAT csv)") as copy:
        for batch in data.select(names).to_batches(max_chunksize=CSV_BATCH_ROWS):
            buffer = io.BytesIO()
            pacsv.write_csv(batch, buffer, write_options=options)
            copy.write(buffer.getvalue())
    return data.num_rows


def check_loaded(cur):
    """적재 후 확인. 문제 목록을 돌려준다 (PK·FK·CHECK 는 적재 중에 DB 가 이미 확인함)."""
    problems = []
    cur.execute("""
        SELECT count(*) FROM (SELECT DISTINCT item_seq, mixture_item_seq FROM gold.drug_contraindication) p
        WHERE NOT EXISTS (SELECT 1 FROM gold.drug_contraindication r
                          WHERE r.item_seq = p.mixture_item_seq AND r.mixture_item_seq = p.item_seq)""")
    one_way = cur.fetchone()[0]
    if one_way:
        problems.append(f"drug_contraindication: 반대 방향이 없는 쌍 {one_way:,}개")
    for a, b, expected in OFFICIAL_CASES:
        cur.execute("SELECT count(*) FROM gold.drug WHERE item_seq IN (%s, %s)", (a, b))
        if cur.fetchone()[0] < 2:
            log(f"  공식 사례 {a} × {b}: 제품이 없어 건너뜀")
            continue
        cur.execute("SELECT array_agg(DISTINCT basis) FROM gold.drug_contraindication "
                    "WHERE item_seq = %s AND mixture_item_seq = %s", (a, b))
        found = cur.fetchone()[0] or []
        if (expected is None and found) or (expected is not None and expected not in found):
            problems.append(f"공식 사례 {a} × {b}: 기대 {expected}, 실제 {found}")
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


def loaded_silver(cur):
    """gold 에 마지막으로 적재한 silver 의 written_at. gold 가 없거나 예전 구조면 None."""
    cur.execute("SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'gold' AND table_name = 'load_info' AND column_name = 'silver_written_at'")
    if cur.fetchone() is None:
        return None
    cur.execute("SELECT silver_written_at FROM gold.load_info")
    row = cur.fetchone()
    return row[0] if row else None


def load(conn, root, force=False):
    """gold 를 다시 만든다. 이미 적재한 silver 면 None, 적재했으면 테이블별 행 수를 돌려준다."""
    latest = json.loads((Path(root) / "silver" / "_latest.json").read_text(encoding="utf-8"))
    snapshots = latest["tables"]
    log(f"silver 스냅샷 {snapshots} (작성 {latest['written_at']})")
    with conn.cursor() as cur:
        previous = loaded_silver(cur)
    conn.commit()
    if previous == latest["written_at"] and not force:
        log("이미 적재한 silver 라 건너뜀 (다시 적재하려면 --force)")
        return None
    schema_sql, index_sql = SCHEMA_SQL.read_text(encoding="utf-8").split("-- INDEXES")

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(schema_sql)
        written = {}

        written["drug"] = copy_rows(cur, "drug", DRUG_COLUMNS, iter_drug_rows(root, snapshots["drug_product"]))
        log(f"  drug {written['drug']:,}행")

        sale = pq.read_table(silver_path(root, "drug_product", snapshots["drug_product"]),
                             columns=["item_seq", "sale_status"])
        drug_items = set(sale["item_seq"].to_pylist())
        sale_items = set(sale.filter(pc.equal(sale["sale_status"], "판매"))["item_seq"].to_pylist())
        items, carried_over, excluded = item_level_rows(root, snapshots["dur_contraindication"], drug_items, sale_items)
        item_count = copy_arrow(cur, "drug_contraindication", CONTRAINDICATION_COLUMNS,
                                item_contraindication_table(items))
        carried_rows = sum(v["rows"] for v in carried_over.values())
        rule_count = copy_rows(cur, "drug_contraindication", CONTRAINDICATION_COLUMNS, iter_rule_contraindication_rows(
            root, snapshots["dur_contraindication"], snapshots["drug_product"], items))
        del items
        written["drug_contraindication"] = item_count + rule_count
        log(f"  drug_contraindication {item_count + rule_count:,}행 ({ITEM_LEVEL} {item_count:,} "
            f"(이전 수집에서 유지 {carried_rows:,}), {RULE_LEVEL} {rule_count:,})")
        for previous, info in carried_over.items():
            log(f"    이전 수집 {previous} 에서 유지: 제품 {info['products']:,}개, {info['rows']:,}행")
        if excluded["rows"]:
            log(f"    drug 에 없는 제품이 낀 품목 DUR 제외: 제품 {len(excluded['item_seqs']):,}개, {excluded['rows']:,}행")

        written["drug_dur_caution"] = copy_rows(cur, "drug_dur_caution", DUR_CAUTION_COLUMNS,
                                                iter_dur_caution_rows(root, snapshots["drug_product"]))
        log(f"  drug_dur_caution {written['drug_dur_caution']:,}행")

        written["drug_ingredient"] = copy_rows(cur, "drug_ingredient", DRUG_INGREDIENT_COLUMNS, iter_drug_ingredient_rows(
            root, snapshots["dur_contraindication"], snapshots["drug_product"]))
        log(f"  drug_ingredient {written['drug_ingredient']:,}행")

        written["health_food"] = copy_arrow(cur, "health_food", HEALTH_FOOD_COLUMNS,
                                            health_food_table(root, snapshots["health_food_product"]))
        log(f"  health_food {written['health_food']:,}행")

        cur.execute(index_sql)
        counts = {}
        for table in TABLES:
            cur.execute(f"SELECT count(*) FROM gold.{table}")
            counts[table] = cur.fetchone()[0]
        problems = [f"{t}: DB {counts[t]:,}행 != 보낸 행 {written[t]:,}" for t in TABLES if counts[t] != written[t]]
        problems += check_loaded(cur)
        if problems:
            raise RuntimeError("적재 후 확인 실패 (모두 되돌림): " + "; ".join(problems))
        cur.execute("INSERT INTO gold.load_info (silver_snapshot, silver_written_at, spec_version, row_counts, "
                    "carried_over, excluded) VALUES (%s, %s, %s, %s, %s, %s)",
                    (latest["snapshot"], latest["written_at"], latest["spec_version"], json.dumps(counts),
                     json.dumps(carried_over), json.dumps(excluded)))
    return counts


def main():
    parser = argparse.ArgumentParser(description="silver → gold 적재")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--host", help="DB 호스트 덮어쓰기 (SSM 터널이면 localhost)")
    parser.add_argument("--dsn", help="Secrets Manager 대신 이 접속 문자열 사용")
    parser.add_argument("--force", action="store_true", help="이미 적재한 silver 여도 다시 적재")
    args = parser.parse_args()

    import psycopg

    conninfo = args.dsn or connection_info(args.host)
    try:
        # 꺼진 RDS 는 기다려도 응답이 없으므로 빨리 실패한다 (제한이 없으면 4분 넘게 기다림)
        conn = (psycopg.connect(conninfo, connect_timeout=CONNECT_TIMEOUT_SECONDS) if isinstance(conninfo, str)
                else psycopg.connect(**conninfo, connect_timeout=CONNECT_TIMEOUT_SECONDS))
    except psycopg.OperationalError as error:
        log(f"DB 접속 실패 — RDS 가 꺼져 있거나, SSM 터널(--host localhost)·접속 정보를 확인할 것: {error}")
        sys.exit(2)
    with conn:
        log("적재 시작 (실패하면 기존 gold 유지)")
        counts = load(conn, args.root, args.force)
    if counts is not None:
        log(f"완료 {counts}")


if __name__ == "__main__":
    main()

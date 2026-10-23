"""S3 Silver → S3 Gold 빌드 (명세: docs/gold_table_spec.md, 테이블 정의: schema.sql). RDS 적재는 load.py.

s3://{버킷}/silver/_latest.json 의 스냅샷(과 "이전 수집 유지"에 쓰는 이전 병용금기 스냅샷 최대 3개)을 임시 폴더로 받아
gold 테이블 6개를 parquet 로 만들고, 검사를 통과하면 S3 에 올린다.

  python pipeline/gold/build.py            # 이미 만든 silver(written_at 같음)면 건너뜀
  python pipeline/gold/build.py --force    # 코드를 바꿨을 때 다시 만들기

출력: s3://{버킷}/gold/{테이블}/snapshot={silver 날짜}/data.parquet
      s3://{버킷}/gold/_latest.json  ← 검사(행 수·양방향 쌍·공식 사례)를 통과하고 파일을 다 올린 뒤 마지막에 갱신.
                                      silver 정보, 테이블별 행 수, 이전 수집 유지·제외 내역을 담는다
메모리: 테이블 하나씩, silver 를 BATCH_ROWS 행 단위로 읽어 WRITE_BATCH_ROWS 행씩 파일에 쓴다 (약 0.9GB)
"""

import argparse
import re
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s3store import Store  # noqa: E402

BATCH_ROWS = 1000        # silver 를 읽는 단위 (허가 문서가 커서 작게)
RULE_BATCH_ROWS = 50000  # 성분 규칙을 거르는 단위
WRITE_BATCH_ROWS = 5000  # gold 파일에 한 번에 쓰는 행 수

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

# 테이블별 (컬럼, DB 타입). 순서 = schema.sql 컬럼 순서 (id 제외). gold 파일도 이 순서·타입 (text[] = 문자열 목록)
DRUG_COLUMNS = [
    ("item_seq", "text"), ("item_name", "text"), ("item_eng_name", "text"), ("entp_name", "text"),
    ("sale_status", "text"), ("etc_otc_name", "text"), ("class_code", "text"), ("class_name", "text"),
    ("atc_code", "text"), ("main_item_ingr", "text"), ("chart", "text"), ("route", "text"), ("image_url", "text"),
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
INGREDIENT_RULE_COLUMNS = [
    ("ingr_code", "text"), ("caution_type", "text"), ("ingr_name", "text"), ("mix_type", "text"),
    ("mix_ingr", "text"), ("form_name", "text"), ("route", "text"), ("max_qty", "text"), ("sers_name", "text"),
    ("prohbt_content", "text"), ("remark", "text"), ("notification_date", "date"), ("source_key", "text"),
]
HEALTH_FOOD_COLUMNS = [
    ("prdlst_report_no", "text"), ("prdlst_nm", "text"), ("bssh_nm", "text"), ("permit_date", "date"),
    ("prdt_shap_cd_nm", "text"), ("dispos", "text"), ("primary_fnclty", "text"), ("ntk_mthd", "text"),
    ("iftkn_atnt_matr_cn", "text"), ("rawmtrl_nm", "text"), ("cstdy_mthd", "text"), ("pog_daycnt", "text"),
]
TABLE_COLUMNS = {
    "drug": DRUG_COLUMNS, "drug_contraindication": CONTRAINDICATION_COLUMNS, "drug_dur_caution": DUR_CAUTION_COLUMNS,
    "drug_ingredient": DRUG_INGREDIENT_COLUMNS, "dur_ingredient_rule": INGREDIENT_RULE_COLUMNS,
    "health_food": HEALTH_FOOD_COLUMNS,
}
TABLES = list(TABLE_COLUMNS)  # RDS 적재 순서 (FK: drug 먼저)
ARROW_TYPES = {"text": pa.string(), "date": pa.date32(), "text[]": pa.list_(pa.string())}

DRUG_SOURCE_COLUMNS = [
    "item_seq", "item_name", "item_eng_name", "entp_name", "sale_status", "etc_otc_name", "prduct_type",
    "atc_code", "main_item_ingr", "chart", "big_prdt_img_url", "pills", "item_permit_date", "easy_info",
    "doc_efficacy", "doc_dosage", "doc_precautions", *CAUTION_COLUMNS,
]

# 복용 경로 (경구 / 경구 외). 경구 외를 먼저 본다: '질정'·'정주'처럼 '정' 이 들어가도 경구가 아닌 것이 있다
NON_ORAL = re.compile(r"주사|수액|주$|주\d|주\[|바이알|앰플|연고|크림|피부|겔제|겔$|첩부|패취|패치|플라스타|"
                      r"카타플라스마|경피|점안|점이|점비|안약|분무|흡입|에어로|에어졸|좌제|좌약|질정|질용|질좌|질서방|"
                      r"관장|로션|외용|가글|스프레이|폼|직장|이식|파스|양치|구강용액|구강세정|프리필드|펜$|의료용")
ORAL = re.compile(r"정|캡슐|캅셀|캅슐|시럽|경구|내복|산제|과립|세립|트로키|츄어블|저작|현탁|엘릭서|액상|환|"
                  r"스팬슐|드링크|내용액|구강붕해|구강용해|연조엑스|산$")
# 제형·이름·성상으로 모를 때 경구 외로 보는 약효분류: 외피용약 026xx, 안과용제, 이비과용제, 치과구강용약, 치질용제
LOCAL_USE_CLASSES = ("01310", "01320", "02310", "02560")
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


def route_of(text):
    if not text:
        return None
    if "경구" in text:  # '경구용겔' 처럼 경구라고 적힌 것은 경구
        return "경구"
    if NON_ORAL.search(text):
        return "경구 외"
    if ORAL.search(text):
        return "경구"
    return None


def product_route(p, class_code, item_form):
    """제품의 복용 경로. 제형(낱알식별·DUR 주의·품목 병용금기) → 제품명(괄호 뺌) → 성상 순으로 처음 판단되는 것.
    모두 모르면 국소 외용 약효분류는 경구 외, 그 밖은 None (모름).
    로컬 확인(2026-10-22): 제형으로 정한 제품의 제품명·성상 판단과 일치 99% 이상."""
    forms = [x["form_code_name"] for x in p["pills"] or []]
    forms += [x.get("form_name") for column in CAUTION_COLUMNS for x in p[column] or []]
    # 성상의 '결정성 분말' 은 정제가 아니다
    chart = (p["chart"] or "").replace("결정", "")
    for text in (*forms, item_form, re.sub(r"\(.*?\)", "", p["item_name"] or ""), chart):
        route = route_of(text)
        if route:
            return route
    if class_code and (class_code.startswith("026") or class_code in LOCAL_USE_CLASSES):
        return "경구 외"
    return None


def rule_route(form_name):
    """용량주의 규칙의 제형 → 경로. 제형이 여럿이면 ('정제/캡슐/용액주사제') 하나라도 경구면 경구.
    제형이 없으면 None."""
    routes = {route_of(part.strip()) for part in re.split(r"[/,]", form_name or "")}
    return "경구" if "경구" in routes else "경구 외" if "경구 외" in routes else None


def drug_row(p, item_forms):
    class_code, class_name = split_class(p["prduct_type"])
    easy = p["easy_info"] or {}
    return {
        "item_seq": p["item_seq"], "item_name": p["item_name"], "item_eng_name": p["item_eng_name"],
        "entp_name": p["entp_name"], "sale_status": p["sale_status"], "etc_otc_name": p["etc_otc_name"],
        "class_code": class_code, "class_name": class_name, "atc_code": p["atc_code"],
        "main_item_ingr": p["main_item_ingr"], "chart": p["chart"],
        "route": product_route(p, class_code, item_forms.get(p["item_seq"])), "image_url": first_image(p),
        "item_permit_date": p["item_permit_date"],
        "easy_efcy": easy.get("efcy"), "easy_use_method": easy.get("use_method"),
        "easy_atpn_warn": easy.get("atpn_warn"), "easy_atpn": easy.get("atpn"), "easy_intrc": easy.get("intrc"),
        "easy_se": easy.get("se"), "easy_deposit_method": easy.get("deposit_method"),
        "doc_efficacy": document_text(p["doc_efficacy"]), "doc_dosage": document_text(p["doc_dosage"]),
        "doc_precautions": document_text(p["doc_precautions"]),
    }


def read_item_forms(root, snapshot):
    """품목 병용금기에 적힌 제품별 제형 {item_seq: 제형} (양쪽 제품 모두, 처음 나온 값)."""
    t = pq.read_table(silver_path(root, "dur_contraindication", snapshot),
                      columns=["item_seq", "form_name", "mixture_item_seq", "mixture_form_name"],
                      filters=[("level", "=", "품목")])
    forms = {}
    for side in ("", "mixture_"):
        pairs = t.select([f"{side}item_seq", f"{side}form_name"]).group_by(
            [f"{side}item_seq"]).aggregate([(f"{side}form_name", "min")])
        for item_seq, form in zip(pairs[f"{side}item_seq"].to_pylist(), pairs[f"{side}form_name_min"].to_pylist()):
            if form:
                forms.setdefault(item_seq, form)
    return forms


def iter_drug_rows(root, snapshot, contraindication_snapshot):
    item_forms = read_item_forms(root, contraindication_snapshot)
    for batch in iter_batches(silver_path(root, "drug_product", snapshot), DRUG_SOURCE_COLUMNS):
        yield from (drug_row(p, item_forms) for p in batch)


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
        "ingr_code": items["ingr_code"], "ingr_names": items["ingr_names"],
        "mixture_ingr_code": items["mixture_ingr_code"], "mixture_ingr_names": items["mixture_ingr_names"],
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
            batch_size=RULE_BATCH_ROWS, columns=["level", "is_rule_valid", *RULE_COLUMNS]):
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


def read_ingredient_rules(root, snapshot):
    """유효한 성분 규칙 효능군중복·용량주의 (silver dur_ingredient_rule)."""
    t = pq.read_table(silver_path(root, "dur_ingredient_rule", snapshot))
    return t.filter(pc.fill_null(t["is_rule_valid"], False)).to_pylist()


def ingredient_rule_table(rules):
    return pa.Table.from_pylist([{
        "ingr_code": r["ingr_code"], "caution_type": r["type_name"], "ingr_name": r["ingr_name"],
        "mix_type": r["mix_type"], "mix_ingr": r["mix_ingr"], "form_name": r["form_name"],
        "route": rule_route(r["form_name"]), "max_qty": r["max_qty"],
        "sers_name": r["sers_name"], "prohbt_content": r["prohbt_content"], "remark": r["remark"],
        "notification_date": r["notification_date"], "source_key": r["dur_seq"],
    } for r in rules], pa.schema([(name, ARROW_TYPES[type_]) for name, type_ in INGREDIENT_RULE_COLUMNS]))


def iter_drug_ingredient_rows(root, snapshot, product_snapshot, rule_snapshot):
    """제품별 성분 (동일 성분 중복 판정용).

    같은 성분 키: DUR 성분 코드(D코드). 원료 코드(M코드)가 D코드로 매핑되지 않으면 정리한 원료 이름.
    매핑 출처: 성분 병용금기 규칙·성분 규칙(효능군중복·용량주의)의 단일 성분 원료 코드
    + 단일 성분 제품의 품목 병용금기·DUR 주의 (제품 M코드 1개 ↔ 규칙 D코드).
    아세트아미노펜처럼 원료 코드가 제형별로 여러 개인 성분은, 매핑된 원료와 정리한 이름이 같으면 같은 D코드로 본다.
    """
    rules = read_valid_rules(root, snapshot)
    m_to_d = rule_m_to_d(rules)
    d_names = {}
    for r in rules:
        for side in ("", "mixture_"):
            if r[f"{side}ingr_names"]:
                d_names.setdefault(r[f"{side}ingr_code"], r[f"{side}ingr_names"][0])
    ingredient_rules = [r for r in read_ingredient_rules(root, rule_snapshot) if r["mix_type"] == "단일"]
    for r in ingredient_rules:
        for m in r["ori_ingr_codes"] or []:
            m_to_d.setdefault(m, set()).add(r["ingr_code"])

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
    # 성분 규칙(효능군중복·용량주의)의 이름은 다른 출처에 이름이 없는 D코드에만 쓴다 (기존 성분 이름이 바뀌지 않게)
    for r in ingredient_rules:
        if r["ingr_name"]:
            d_names.setdefault(r["ingr_code"], r["ingr_name"])

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


# ---------------------------------------------------------------- 저장·검사

def gold_path(root, table, snapshot):
    return Path(root) / "gold" / table / f"snapshot={snapshot}" / "data.parquet"


def write_table(path, columns, *parts):
    """arrow 테이블 또는 행(dict) 반복자들을 이어서 parquet 하나로 쓴다. 행 수를 돌려준다."""
    schema = pa.schema([(name, ARROW_TYPES[type_]) for name, type_ in columns])
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with pq.ParquetWriter(path, schema) as writer:
        for part in parts:
            if isinstance(part, pa.Table):
                writer.write_table(part.select(schema.names).cast(schema))
                count += part.num_rows
                continue
            batch = []
            for row in part:
                batch.append(row)
                if len(batch) == WRITE_BATCH_ROWS:
                    writer.write_table(pa.Table.from_pylist(batch, schema))
                    count += len(batch)
                    batch = []
            if batch:
                writer.write_table(pa.Table.from_pylist(batch, schema))
                count += len(batch)
    return count


def check_gold(root, snapshot):
    """만든 gold 확인. 문제 목록을 돌려준다."""
    problems = []
    pairs = pq.read_table(gold_path(root, "drug_contraindication", snapshot),
                          columns=["item_seq", "mixture_item_seq", "basis"])
    pairs = pairs.group_by(["item_seq", "mixture_item_seq"]).aggregate([("basis", "distinct")])  # 한 번에 묶어야 짝이 맞는다
    reverse = pairs.select(["mixture_item_seq", "item_seq"]).rename_columns(["item_seq", "mixture_item_seq"])
    one_way = pairs.select(["item_seq", "mixture_item_seq"]).join(
        reverse, keys=["item_seq", "mixture_item_seq"], join_type="left anti").num_rows
    if one_way:
        problems.append(f"drug_contraindication: 반대 방향이 없는 쌍 {one_way:,}개")
    self_pairs = pc.sum(pc.equal(pairs["item_seq"], pairs["mixture_item_seq"])).as_py() or 0
    if self_pairs:
        problems.append(f"drug_contraindication: 자기 자신과의 쌍 {self_pairs:,}개")

    drugs = set(pq.read_table(gold_path(root, "drug", snapshot), columns=["item_seq"])["item_seq"].to_pylist())
    bases = {(a, b): set(found) for a, b, found in zip(
        pairs["item_seq"].to_pylist(), pairs["mixture_item_seq"].to_pylist(), pairs["basis_distinct"].to_pylist())
        if (a, b) in {(x, y) for x, y, _ in OFFICIAL_CASES}}
    for a, b, expected in OFFICIAL_CASES:
        if a not in drugs or b not in drugs:
            log(f"  공식 사례 {a} × {b}: 제품이 없어 건너뜀")
            continue
        found = bases.get((a, b), set())
        if (expected is None and found) or (expected is not None and expected not in found):
            problems.append(f"공식 사례 {a} × {b}: 기대 {expected}, 실제 {sorted(found)}")
    return problems


def build(root, latest):
    """root/silver 로 root/gold 에 테이블 6개를 만든다. gold/_latest.json 내용을 돌려준다."""
    snapshots = latest["tables"]
    snapshot = latest["snapshot"]
    counts = {}

    def out(table):
        return gold_path(root, table, snapshot)

    counts["drug"] = write_table(out("drug"), DRUG_COLUMNS, iter_drug_rows(
        root, snapshots["drug_product"], snapshots["dur_contraindication"]))
    log(f"  drug {counts['drug']:,}행")

    sale = pq.read_table(silver_path(root, "drug_product", snapshots["drug_product"]), columns=["item_seq", "sale_status"])
    drug_items = set(sale["item_seq"].to_pylist())
    sale_items = set(sale.filter(pc.equal(sale["sale_status"], "판매"))["item_seq"].to_pylist())
    items, carried_over, excluded = item_level_rows(root, snapshots["dur_contraindication"], drug_items, sale_items)
    item_count = items.num_rows
    counts["drug_contraindication"] = write_table(
        out("drug_contraindication"), CONTRAINDICATION_COLUMNS, item_contraindication_table(items),
        iter_rule_contraindication_rows(root, snapshots["dur_contraindication"], snapshots["drug_product"], items))
    del items
    carried_rows = sum(v["rows"] for v in carried_over.values())
    log(f"  drug_contraindication {counts['drug_contraindication']:,}행 ({ITEM_LEVEL} {item_count:,} "
        f"(이전 수집에서 유지 {carried_rows:,}), {RULE_LEVEL} {counts['drug_contraindication'] - item_count:,})")
    for previous, info in carried_over.items():
        log(f"    이전 수집 {previous} 에서 유지: 제품 {info['products']:,}개, {info['rows']:,}행")
    if excluded["rows"]:
        log(f"    drug 에 없는 제품이 낀 품목 DUR 제외: 제품 {len(excluded['item_seqs']):,}개, {excluded['rows']:,}행")

    counts["drug_dur_caution"] = write_table(out("drug_dur_caution"), DUR_CAUTION_COLUMNS,
                                             iter_dur_caution_rows(root, snapshots["drug_product"]))
    log(f"  drug_dur_caution {counts['drug_dur_caution']:,}행")

    counts["drug_ingredient"] = write_table(out("drug_ingredient"), DRUG_INGREDIENT_COLUMNS, iter_drug_ingredient_rows(
        root, snapshots["dur_contraindication"], snapshots["drug_product"], snapshots["dur_ingredient_rule"]))
    log(f"  drug_ingredient {counts['drug_ingredient']:,}행")

    counts["dur_ingredient_rule"] = write_table(out("dur_ingredient_rule"), INGREDIENT_RULE_COLUMNS,
                                                ingredient_rule_table(read_ingredient_rules(
                                                    root, snapshots["dur_ingredient_rule"])))
    log(f"  dur_ingredient_rule {counts['dur_ingredient_rule']:,}행")

    counts["health_food"] = write_table(out("health_food"), HEALTH_FOOD_COLUMNS,
                                        health_food_table(root, snapshots["health_food_product"]))
    log(f"  health_food {counts['health_food']:,}행")

    problems = [f"{t}: 파일 {pq.ParquetFile(out(t)).metadata.num_rows:,}행 != 쓴 행 {counts[t]:,}"
                for t in TABLES if pq.ParquetFile(out(t)).metadata.num_rows != counts[t]]
    problems += check_gold(root, snapshot)
    if problems:
        raise RuntimeError("gold 검사 실패 (S3 에 올리지 않음): " + "; ".join(problems))
    return {
        "snapshot": snapshot, "silver_tables": snapshots, "silver_written_at": latest["written_at"],
        "spec_version": latest["spec_version"], "row_counts": counts, "carried_over": carried_over,
        "excluded": excluded, "written_at": datetime.now().isoformat(timespec="seconds"),
    }


def download_silver(store, root, latest):
    """이번 silver 스냅샷과, 이전 수집 유지에 쓸 이전 병용금기 스냅샷(최대 CARRY_OVER_SNAPSHOTS 개)을 받는다."""
    for table, snapshot in latest["tables"].items():
        path = f"silver/{table}/snapshot={snapshot}/"
        store.download_prefix(path, Path(root) / path)
    table = "dur_contraindication"
    current = latest["tables"][table]
    earlier = sorted((name.removeprefix("snapshot=") for name in store.folders(f"silver/{table}/")
                      if name.removeprefix("snapshot=") < current), reverse=True)[:CARRY_OVER_SNAPSHOTS]
    for snapshot in earlier:
        key = f"silver/{table}/snapshot={snapshot}/data.parquet"
        if store.list(key):
            store.download_prefix(key, Path(root) / key)
    log(f"silver 받음: {latest['tables']}, 이전 {table} {earlier or '없음'}")


def main():
    parser = argparse.ArgumentParser(description="S3 silver → S3 gold")
    parser.add_argument("--bucket")
    parser.add_argument("--force", action="store_true", help="이미 만든 silver 여도 다시 만들기")
    parser.add_argument("--work", help="임시 폴더 (지정하면 끝나도 지우지 않음. 기본: 새 임시 폴더를 만들고 끝나면 삭제)")
    args = parser.parse_args()

    store = Store(args.bucket)
    latest = store.get_json("silver/_latest.json")
    if latest is None:
        sys.exit(f"s3://{store.bucket}/silver/_latest.json 없음 — silver 를 먼저 만들 것")
    built = store.get_json("gold/_latest.json")
    if built and built["silver_written_at"] == latest["written_at"] and not args.force:
        log(f"이미 만든 silver(작성 {latest['written_at']})라 건너뜀 (다시 만들려면 --force)")
        return
    root = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="pill-gold-"))
    log(f"silver {latest['tables']} (작성 {latest['written_at']}) → gold, 버킷 {store.bucket}, 임시 폴더 {root}")
    try:
        download_silver(store, root, latest)
        info = build(root, latest)
        for table in TABLES:
            store.upload_dir(gold_path(root, table, info["snapshot"]).parent,
                             f"gold/{table}/snapshot={info['snapshot']}/", log=log)
        store.put_json("gold/_latest.json", info)
        log(f"s3://{store.bucket}/gold/_latest.json → {info['snapshot']} (마지막) {info['row_counts']}")
    except RuntimeError as error:
        log(str(error))
        sys.exit(1)
    finally:
        if not args.work:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()

"""Bronze → Silver 빌드 (명세: docs/silver_table_spec.md, 원본별 정리 명세: tables.py).

silver 테이블 3개:
  drug_product            의약품 통합 (제품 1개 = 1행, 판매·판매중지만). 허가·e약은요·낱알식별·DUR 주의·허가 문서
  dur_contraindication    병용금기 (gold 판정용). level = 성분(성분 A × B 규칙) / 품목(제품 A × B 쌍)
  health_food_product     건강기능식품 (식품안전나라 C003)

  python pipeline/silver/build.py                       # 모든 원본에 공통인 최신 스냅샷으로 전체 빌드
  python pipeline/silver/build.py --snapshot 2026-10-13
  python pipeline/silver/build.py health_food_product   # 일부만 다시 만들기 (_latest.json 은 건드리지 않음)

출력: {root}/silver/{table}/snapshot={날짜}/data.parquet, _meta.json
      {root}/silver/{table}/snapshot={날짜}/_rejects.json   (변환 실패 값이 있을 때만)
      {root}/silver/_latest.json  ← 전체 빌드가 모두 검증을 통과했을 때만 마지막에 갱신
"""

import argparse
import gc
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from dur_link import LINKED, MULTIPLE, link_rule
from tables import (
    ALL_TABLE_NAMES, CONTRAINDICATION_TABLE, DOC_SOURCE_COLUMNS, DRUG_PRODUCT_TABLE, DUR_INGR_TABLES,
    DUR_INGR_USJNT, DUR_ITEM_CAUTION_TABLES, DUR_ITEM_EFCY_DPLCT, DUR_ITEM_MASTER, DUR_ITEM_SEOBANGJEONG,
    DUR_ITEM_USJNT, EASY_DRUG, EASY_TEXT_FIELDS, OUTPUT_TABLES,
    PERMIT_DETAIL, PERMIT_INGREDIENT, PERMIT_ITEM, PILL_IDENTIFICATION, SPEC_VERSION,
)

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "s3"
PLACEHOLDER_NULL = {"PROHBT_CONTENT": {"-", "_"}}  # 내용 없음을 뜻하는 자리표시 값
ARROW_TYPES = {
    "str": pa.string(), "int": pa.int64(), "float": pa.float64(), "date": pa.date32(), "bool": pa.bool_(),
    "list": pa.list_(pa.string()),
}
DERIVED_SOURCES = {"is_active": ("CANCEL_NAME",), "is_rule_valid": ("DEL_YN",),
                   "pair_key": ("INGR_CODE", "MIXTURE_INGR_CODE")}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# 허가 상태 → 판매 상태. 여기 없는 상태(취하·폐업·취소 등)의 제품은 drug_product 에 넣지 않는다
SALE_STATUS = {"정상": "판매", "유효기간만료": "판매중지"}


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- bronze 읽기

def unwrap_items(body):
    items = body.get("items")
    if not items:
        return []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    # DUR 성분 응답은 {"item": {...}} 로 한 겹 더 싸여 있다
    return [i["item"] if isinstance(i, dict) and list(i) == ["item"] else i for i in items]


def response_total(response, operation):
    if operation in response:  # 식품안전나라: {"C003": {"total_count", "row"}}
        return int(response[operation]["total_count"])
    return int(response["body"]["totalCount"])


def response_items(response, operation):
    if operation in response:
        return response[operation].get("row") or []
    return unwrap_items(response["body"])


def complete_pages(root, operation, snapshot):
    """스냅샷의 페이지 경로 목록과 전체 건수. 페이지가 빠졌으면 실패."""
    dirs = list((root / "bronze").glob(f"*/{operation}/snapshot={snapshot}"))
    if len(dirs) != 1:
        raise BuildError(f"[{operation}] bronze snapshot={snapshot} 폴더가 {len(dirs)}개")
    pages = {}
    for path in dirs[0].glob("page_*.json"):
        match = re.fullmatch(r"page_(\d+)\.json", path.name)
        if match:
            pages[int(match.group(1))] = path
    if 1 not in pages:
        raise BuildError(f"[{operation}] 1쪽이 없음")
    first = json.loads(pages[1].read_text(encoding="utf-8"))
    total = response_total(first["response"], operation)
    expected = set(range(1, math.ceil(total / first["meta"]["num_of_rows"]) + 1))
    if set(pages) != expected:
        raise BuildError(f"[{operation}] 페이지 불일치: 없음 {sorted(expected - set(pages))[:10]}, "
                         f"남음 {sorted(set(pages) - expected)[:10]}")
    return [pages[n] for n in sorted(pages)], total


def iter_pages(root, operation, snapshot):
    """페이지마다 항목 목록(컬럼명 앞뒤 공백 제거)을 돌려주고, 끝나면 건수를 전체 건수와 대조한다."""
    paths, total = complete_pages(root, operation, snapshot)
    count = 0
    for path in paths:
        items = response_items(json.loads(path.read_text(encoding="utf-8"))["response"], operation)
        count += len(items)
        yield [{name.strip(): value for name, value in item.items()} for item in items]
    if count != total:
        raise BuildError(f"[{operation}] 항목 수 {count} != 전체 건수 {total}")


def clean(name, value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in PLACEHOLDER_NULL.get(name, ()):
        return None
    return text


def load_source(root, operation, snapshot, skip=()):
    """오퍼레이션 전체를 문자열 컬럼 테이블로 읽는다 (페이지 단위로 만들어 이어 붙여 메모리를 아낀다)."""
    parts = []
    for items in iter_pages(root, operation, snapshot):
        names = []
        for item in items:
            for name in item:
                if name not in skip and name not in names:
                    names.append(name)
        parts.append(pa.table({name: pa.array([clean(name, item.get(name)) for item in items], type=pa.string())
                               for name in names}))
    return pa.concat_tables(parts, promote_options="default")


def latest_common_snapshot(root, operations):
    common = None
    for operation in operations:
        found = {p.name.removeprefix("snapshot=") for p in (root / "bronze").glob(f"*/{operation}/snapshot=*")}
        common = found if common is None else common & found
    if not common:
        raise BuildError("모든 원본에 공통인 bronze 스냅샷이 없음")
    return max(common)


# ---------------------------------------------------------------- 값 변환

def parse_date(text):
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{4})([A-Za-z]+?)(\d{1,2})(?:st|nd|rd|th)?", text)  # 2021February18th
    if match and match.group(2)[:3].lower() in MONTHS:
        return date(int(match.group(1)), MONTHS[match.group(2)[:3].lower()], int(match.group(3)))
    raise ValueError(text)


def parse_number(text, kind):
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", text):  # 천 단위 쉼표
        text = text.replace(",", "")
    return int(text) if kind == "int" else float(text)


def parse_codes(text):
    codes = []
    for code in re.findall(r"\[([A-Za-z0-9]+)\]", text):
        if code not in codes:
            codes.append(code)
    return codes


def split_bracket(text):
    match = re.fullmatch(r"\[([^\]]*)\](.*)", text, re.S)
    return (match.group(1).strip() or None, match.group(2).strip() or None) if match else (None, text)


PARSERS = {
    "date": parse_date,
    "int": lambda text: parse_number(text, "int"),
    "float": lambda text: parse_number(text, "float"),
    "comma": lambda text: [part.strip() for part in text.split(",") if part.strip()],
    "codes": parse_codes,
    "bracket_code": lambda text: split_bracket(text)[0],
    "bracket_name": lambda text: split_bracket(text)[1],
    "last_path": lambda text: text.rstrip("/").rsplit("/", 1)[-1],
}


def convert(column, col, rejects):
    """고유값마다 한 번씩만 변환한다 (80만 행이어도 고유값은 적다). 실패한 값은 null + rejects."""
    array = column.combine_chunks() if isinstance(column, pa.ChunkedArray) else column
    if col.parse is None:
        return array
    parser = PARSERS[col.parse]
    encoded = pc.dictionary_encode(array)
    converted, failed = [], {}
    for index, value in enumerate(encoded.dictionary.to_pylist()):
        try:
            converted.append(parser(value))
        except (ValueError, TypeError):
            converted.append(None)
            failed[index] = value
    if failed:
        counts = {c["values"]: c["counts"] for c in pc.value_counts(encoded.indices).to_pylist()}
        rejects += [{"column": col.name, "raw_value": value, "rows": counts.get(index, 0)}
                    for index, value in failed.items()]
    return pa.array(converted, type=ARROW_TYPES[col.type]).take(encoded.indices)


def stable_hash(values):
    """정체성 값들의 해시. 이 규칙을 바꾸면 모든 키가 바뀌므로 고치지 않는다."""
    text = "\x1e".join("\x00" if value is None else value for value in values)
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def sorted_lists(column):
    return pa.array([sorted(values) if values else None for values in column.to_pylist()],
                    type=pa.list_(pa.string()))


# ---------------------------------------------------------------- 원본 오퍼레이션 정리

def collapse(t, table):
    """collapse_key 가 같은 행을 1행으로. collected 컬럼은 목록으로 모으고, 나머지는 값이 하나여야 한다
    (resolve 에 적힌 컬럼만 예외: 우선값이 있는 행의 값을 쓴다)."""
    key = list(table.collapse_key)
    collected = [c.src for c in table.columns if c.parse == "collected"]
    others = [name for name in t.column_names if name not in key and name not in collected]
    if table.resolve:
        ranks = []
        for i, (name, preferred) in enumerate(table.resolve.items()):
            rank = pc.is_null(t[name]) if preferred is None else pc.fill_null(pc.not_equal(t[name], preferred), True)
            t = t.append_column(f"__rank{i}", rank)
            ranks.append(f"__rank{i}")
        t = t.sort_by([(name, "ascending") for name in ranks]).drop_columns(ranks)
    aggregations = [(name, "distinct", pc.CountOptions(mode="only_valid")) for name in collected]
    aggregations += [(name, "count_distinct", pc.CountOptions(mode="all")) for name in others]
    aggregations += [(name, "first") for name in others]
    grouped = t.group_by(key, use_threads=False).aggregate(aggregations)
    for name in others:
        if name in table.resolve:
            continue
        conflicts = pc.sum(pc.greater(grouped[f"{name}_count_distinct"], 1)).as_py() or 0
        if conflicts:
            raise BuildError(f"[{table.name}] {key} 가 같은데 {name} 값이 다른 그룹 {conflicts}개")
    columns = {}
    for name in t.column_names:
        if name in key:
            columns[name] = grouped[name]
        elif name in collected:
            columns[name] = sorted_lists(grouped[f"{name}_distinct"])
        else:
            columns[name] = grouped[f"{name}_first"]
    return pa.table(columns), t.num_rows - grouped.num_rows


def derive(name, t, table):
    if name == "is_active":
        return pc.equal(t["CANCEL_NAME"], "정상")
    if name == "is_rule_valid":
        return pc.equal(t["DEL_YN"], "정상")
    if name == "rule_key":
        columns = [t[c].to_pylist() for c in table.rule_key]
        return pa.array([stable_hash(values) for values in zip(*columns)], type=pa.string())
    if name == "pair_key":
        return pa.array([None if a is None or b is None else "|".join(sorted([a, b]))
                         for a, b in zip(t["INGR_CODE"].to_pylist(), t["MIXTURE_INGR_CODE"].to_pylist())],
                        type=pa.string())
    raise BuildError(f"[{table.name}] 알 수 없는 파생 컬럼 {name}")


def validate(out, name, primary_key, required):
    for column in required:
        nulls = out[column].null_count
        if nulls:
            raise BuildError(f"[{name}] 필수 컬럼 {column}에 null {nulls}건")
    for column in primary_key:
        if out[column].null_count:
            raise BuildError(f"[{name}] PK 컬럼 {column}에 null")
    distinct = out.select(list(primary_key)).group_by(list(primary_key)).aggregate([]).num_rows
    if distinct != out.num_rows:
        raise BuildError(f"[{name}] PK {primary_key} 중복 {out.num_rows - distinct}건")


def build_table(table, raw, snapshot):
    """원본 오퍼레이션 → 정리된 테이블. (결과, 메타, rejects, 합친 뒤 원본 형태 테이블)"""
    used = {c.src for c in table.columns if c.src}
    used |= set(table.collapse_key) | set(table.rule_key) | set(table.exclude_when_all_null)
    used |= set(table.same_as) | set(table.resolve)
    for col in table.columns:
        used |= set(DERIVED_SOURCES.get(col.name, ()))
    missing = used - set(raw.column_names)
    if missing:
        raise BuildError(f"[{table.name}] 원본에 없는 컬럼 {sorted(missing)} (API 스키마 변경?)")
    unmapped = sorted(set(raw.column_names) - used - set(table.ignore_source))

    t = raw
    source_rows = t.num_rows
    if table.same_as:
        a, b = (t[name] for name in table.same_as)
        same = pc.fill_null(pc.or_kleene(pc.equal(a, b), pc.and_(pc.is_null(a), pc.is_null(b))), False)
        differ = source_rows - (pc.sum(same.cast(pa.int64())).as_py() or 0)
        if differ:
            raise BuildError(f"[{table.name}] {table.same_as[0]} != {table.same_as[1]} 인 행 {differ}건")

    t = t.group_by(t.column_names, use_threads=False).aggregate([])  # 완전 중복 제거
    exact_duplicates = source_rows - t.num_rows

    excluded = 0
    if table.exclude_when_all_null:
        mask = pc.is_null(t[table.exclude_when_all_null[0]])
        for name in table.exclude_when_all_null[1:]:
            mask = pc.and_(mask, pc.is_null(t[name]))
        excluded = pc.sum(mask.cast(pa.int64())).as_py() or 0
        t = t.filter(pc.invert(mask))

    collapsed = 0
    if table.collapse_key:
        t, collapsed = collapse(t, table)

    rejects = []
    arrays = {}
    for col in table.columns:
        if col.src is None:
            arrays[col.name] = derive(col.name, t, table)
        elif col.parse == "collected":
            arrays[col.name] = t[col.src]
        else:
            arrays[col.name] = convert(t[col.src], col, rejects)
    arrays["snapshot"] = pa.array([date.fromisoformat(snapshot)] * t.num_rows, type=pa.date32())
    schema = pa.schema([(c.name, ARROW_TYPES[c.type]) for c in table.columns] + [("snapshot", pa.date32())])
    out = pa.table(arrays, schema=schema).sort_by([(k, "ascending") for k in table.primary_key])

    validate(out, table.name, table.primary_key, [c.name for c in table.columns if c.required] + ["snapshot"])
    if source_rows != out.num_rows + exact_duplicates + collapsed + excluded:
        raise BuildError(f"[{table.name}] 건수 대조 실패: 원본 {source_rows} != {out.num_rows} + 중복 "
                         f"{exact_duplicates} + 합침 {collapsed} + 제외 {excluded}")
    meta = {
        "table": table.name, "source_operation": table.operation, "snapshot": snapshot,
        "spec_version": SPEC_VERSION, "primary_key": list(table.primary_key),
        "source_rows": source_rows, "rows": out.num_rows, "exact_duplicates_removed": exact_duplicates,
        "collapsed_rows": collapsed, "excluded_rows": excluded,
        "excluded_reason": f"{', '.join(table.exclude_when_all_null)} 가 모두 null" if excluded else None,
        "rejected_values": sum(r["rows"] for r in rejects), "unmapped_source_columns": unmapped,
    }
    return out, meta, rejects, t


def prepare(root, table, snapshot, skip=()):
    out, meta, rejects, prepared = build_table(table, load_source(root, table.operation, snapshot, skip), snapshot)
    return out, meta, rejects, prepared


# ---------------------------------------------------------------- 허가 문서

def strip_html(text):
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)  # 태그만 지운다 ('pH < 7' 같은 본문은 건드리지 않음)
    return html.unescape(text).strip() or None


def parse_doc(xml_text, doc_type):
    """문서 XML → 항목 목록. 항목 본문은 문단들을 줄바꿈으로 이어 붙인 것."""
    root = ET.fromstring(xml_text)
    articles, inside = [], 0
    for section_idx, section in enumerate(root.iter("SECTION"), start=1):
        section_title = clean("", section.get("title"))
        for article_idx, article in enumerate(section.findall("ARTICLE"), start=1):
            article_title = clean("", article.get("title"))
            paragraphs = []
            for paragraph in article.findall("PARAGRAPH"):
                inside += 1
                text = strip_html(paragraph.text or "")
                if text:
                    paragraphs.append(text)
            body = "\n".join(paragraphs) or None
            articles.append({
                "section_idx": section_idx, "section_title": section_title, "article_idx": article_idx,
                "article_title": article_title, "text": body,
                "content_hash": stable_hash([doc_type, section_title, article_title, body]),
            })
    return articles, len(list(root.iter("PARAGRAPH"))) - inside


def load_documents(root, snapshot, item_seqs, stats, rejects):
    """판매·판매중지 제품의 허가 문서만 파싱한다. {item_seq: {doc_type: [항목, …]}}"""
    documents = {}
    for items in iter_pages(root, PERMIT_DETAIL.operation, snapshot):
        for item in items:
            item_seq = clean("ITEM_SEQ", item.get("ITEM_SEQ"))
            if item_seq not in item_seqs:
                continue
            docs = {}
            for source, doc_type in DOC_SOURCE_COLUMNS.items():
                xml_text = clean(source, item.get(source))
                if xml_text is None:
                    continue
                try:
                    articles, outside = parse_doc(xml_text, doc_type)
                except ET.ParseError:
                    stats["doc_parse_failures"] += 1
                    rejects.append({"item_seq": item_seq, "column": source, "raw_value": "XML 파싱 실패"})
                    continue
                stats["documents"] += 1
                stats["doc_articles"] += len(articles)
                stats["doc_paragraphs_outside_structure"] += outside
                docs[doc_type] = articles
            documents[item_seq] = docs
    return documents


# ---------------------------------------------------------------- drug_product 조립

def columns_of(table, names):
    by_name = {c.name: c for c in table.columns}
    return [(name, ARROW_TYPES[by_name[name].type]) for name in names]


def struct_type(fields):
    return pa.struct([pa.field(name, kind) for name, kind in fields])


def group_rows(table, item_seqs, key="item_seq"):
    """정리된 테이블 → {item_seq: [행 dict, …]} (판매·판매중지 제품만). 빠진 행 수도 돌려준다."""
    groups, dropped = defaultdict(list), 0
    for row in table.to_pylist():
        if row[key] in item_seqs:
            groups[row[key]].append(row)
        else:
            dropped += 1
    return groups, dropped


def pick(row, fields):
    return {name: row[name] for name, _ in fields}


ITEM_LEVEL = {  # 제품 단위 정보라 하위 목록에 넣지 않는 컬럼 (기본 정보에 이미 있음)
    "item_seq", "item_name", "item_eng_name", "item_permit_date", "entp_seq", "entp_name", "chart", "etc_otc_name",
    "etc_otc_code", "class_code", "class_name", "main_ingr", "main_ingr_codes", "edi_code", "bizrno", "type_name",
    "snapshot",
}

CAUTION_COLUMNS = {  # 유형 → (drug_product 컬럼 이름, 성분 규칙의 값 컬럼)
    "dur_item_pwnm": ("dur_pregnancy", ["grade"]),
    "dur_item_odsn": ("dur_elderly", []),
    "dur_item_spcify_agrde": ("dur_age", ["age_base"]),
    "dur_item_cpcty": ("dur_dosage", ["max_qty"]),
    "dur_item_mdctn_pd": ("dur_duration", ["max_dosage_term"]),
}
CAUTION_INGR = {"dur_item_pwnm": "dur_ingr_pwnm", "dur_item_odsn": "dur_ingr_odsn",
                "dur_item_spcify_agrde": "dur_ingr_spcify_agrde", "dur_item_cpcty": "dur_ingr_cpcty",
                "dur_item_mdctn_pd": "dur_ingr_mdctn_pd"}
RULE_BASE = ["dur_seq", "mix_type", "mix_ingr", "form_name", "notification_date", "prohbt_content", "remark"]


def build_drug_product(root, snapshot):
    started = time.time()
    rejects, sources = [], {}
    stats = Counter()

    permit_item, meta, r, _ = prepare(root, PERMIT_ITEM, snapshot)
    rejects += r
    sources[PERMIT_ITEM.name] = meta
    sale = {row["item_seq"]: SALE_STATUS[row["cancel_name"]] for row in
            permit_item.select(["item_seq", "cancel_name"]).to_pylist() if row["cancel_name"] in SALE_STATUS}
    removed = Counter(c for c in permit_item["cancel_name"].to_pylist() if c not in SALE_STATUS)
    item_seqs = set(sale)

    # 기본 정보: 허가 목록 + 허가 상세 (같은 이름의 컬럼은 허가 목록 값을 쓴다)
    base_item_cols = [c.name for c in PERMIT_ITEM.columns if c.name != "is_active"]
    permit_detail, meta, r, _ = prepare(root, PERMIT_DETAIL, snapshot, skip=tuple(DOC_SOURCE_COLUMNS))
    rejects += r
    sources[PERMIT_DETAIL.name] = meta
    detail_cols = [c.name for c in PERMIT_DETAIL.columns if c.name not in base_item_cols and c.name != "is_active"]
    detail = {row["item_seq"]: row for row in permit_detail.select(["item_seq", "cancel_name"] + detail_cols).to_pylist()}
    item_status = dict(zip(permit_item["item_seq"].to_pylist(), permit_item["cancel_name"].to_pylist()))
    status_mismatch = sum(1 for s in item_seqs if s in detail and detail[s]["cancel_name"] != item_status[s])
    base_fields = columns_of(PERMIT_ITEM, base_item_cols) + columns_of(PERMIT_DETAIL, detail_cols)

    # 성분
    ingredient_table, meta, r, _ = prepare(root, PERMIT_INGREDIENT, snapshot)
    rejects += r
    sources[PERMIT_INGREDIENT.name] = meta
    ingredient_fields = columns_of(PERMIT_INGREDIENT, ["tamt_seq", "mtral_sn", "mtral_code", "mtral_nm", "qnt",
                                                        "qnt_text", "ingd_unit_cd", "cpnt_ctnt_cont"])
    ingredients, stats["ingredient_rows_dropped"] = group_rows(ingredient_table, item_seqs)

    # 알약
    pill_table, meta, r, _ = prepare(root, PILL_IDENTIFICATION, snapshot)
    rejects += r
    sources[PILL_IDENTIFICATION.name] = meta
    pill_fields = columns_of(PILL_IDENTIFICATION, [c.name for c in PILL_IDENTIFICATION.columns
                                                   if c.name not in ITEM_LEVEL or c.name in ("class_code", "class_name")])
    pills, stats["pill_rows_dropped"] = group_rows(pill_table, item_seqs)

    # e약은요 (7문항은 정리 명세에서 빠져 있어 합친 뒤 원본 형태에서 가져온다)
    easy_table, meta, r, easy_prepared = prepare(root, EASY_DRUG, snapshot)
    rejects += r
    sources[EASY_DRUG.name] = meta
    easy_fields = [(field, pa.string()) for field in EASY_TEXT_FIELDS.values()] + columns_of(
        EASY_DRUG, ["item_images", "open_date", "update_date"])
    easy_text = {row["itemSeq"]: row for row in easy_prepared.select(["itemSeq", *EASY_TEXT_FIELDS]).to_pylist()}
    easy = {}
    for row in easy_table.to_pylist():
        if row["item_seq"] in item_seqs:
            text = easy_text[row["item_seq"]]
            easy[row["item_seq"]] = {**{f: text[s] for s, f in EASY_TEXT_FIELDS.items()},
                                     **pick(row, easy_fields[len(EASY_TEXT_FIELDS):])}
        else:
            stats["easy_rows_dropped"] += 1

    # DUR 품목 마스터
    master_table, meta, r, _ = prepare(root, DUR_ITEM_MASTER, snapshot)
    rejects += r
    sources[DUR_ITEM_MASTER.name] = meta
    dur_fields = columns_of(DUR_ITEM_MASTER, ["class_code", "class_name", "type_code", "type_name", "change_date"])
    dur_info = {}
    for row in master_table.to_pylist():
        if row["item_seq"] in item_seqs:
            dur_info[row["item_seq"]] = pick(row, dur_fields)
        else:
            stats["dur_master_rows_dropped"] += 1

    # DUR 성분 규칙 (유효한 것만, 연결용)
    ingr_rules = {}
    for table in DUR_INGR_TABLES:
        out, meta, r, _ = prepare(root, table, snapshot)
        rejects += r
        sources[table.name] = meta
        ingr_rules[table.name] = [row for row in out.to_pylist() if row["is_rule_valid"]]

    # DUR 주의 (품목 규칙 → 성분 규칙 연결)
    caution_values, caution_types, link_stats = {}, {}, {}
    for table in DUR_ITEM_CAUTION_TABLES:
        column, value_columns = CAUTION_COLUMNS[table.name]
        out, meta, r, _ = prepare(root, table, snapshot)
        rejects += r
        sources[table.name] = meta
        ingr_table = next(t for t in DUR_INGR_TABLES if t.name == CAUTION_INGR[table.name])
        rule_fields = columns_of(ingr_table, RULE_BASE + value_columns)
        entry_fields = [(name, kind) for name, kind in columns_of(table, [c.name for c in table.columns])
                        if name not in ITEM_LEVEL]
        entry_type = struct_type(entry_fields + [("link_status", pa.string()), ("link_method", pa.string()),
                                                 ("ingredient_rules", pa.list_(struct_type(rule_fields)))])
        rules = ingr_rules[ingr_table.name]
        value_column = value_columns[0] if value_columns else None
        grouped, dropped = group_rows(out, item_seqs)
        counts = Counter({"dropped_rows": dropped})
        values = {}
        for item_seq, rows in grouped.items():
            entries = []
            for row in rows:
                status, method, linked = link_rule(row, rules, value_column)
                counts[status] += 1
                counts[f"{status}/{method}"] += 1
                entries.append({**pick(row, entry_fields), "link_status": status, "link_method": method,
                                "ingredient_rules": sorted((pick(x, rule_fields) for x in linked),
                                                           key=lambda x: x["dur_seq"])})
            values[item_seq] = sorted(entries, key=lambda e: (e["ingr_code"], e.get("rule_key") or ""))
        caution_values[column], caution_types[column], link_stats[column] = values, pa.list_(entry_type), dict(counts)

    # 효능군중복: 품목 규칙에 성분 규칙 번호(dur_seq)가 있어 바로 연결
    out, meta, r, _ = prepare(root, DUR_ITEM_EFCY_DPLCT, snapshot)
    rejects += r
    sources[DUR_ITEM_EFCY_DPLCT.name] = meta
    efcy_rules = {row["dur_seq"]: row for row in ingr_rules["dur_ingr_efcy_dplct"]}
    efcy_ingr = next(t for t in DUR_INGR_TABLES if t.name == "dur_ingr_efcy_dplct")
    efcy_rule_fields = columns_of(efcy_ingr, ["dur_seq", "effect_code", "sers_name", "mix_type", "mix_ingr",
                                              "notification_date", "prohbt_content", "remark"])
    efcy_fields = [(name, kind) for name, kind in columns_of(
        DUR_ITEM_EFCY_DPLCT, [c.name for c in DUR_ITEM_EFCY_DPLCT.columns]) if name not in ITEM_LEVEL]
    efcy_type = struct_type(efcy_fields + [("link_status", pa.string()), ("link_method", pa.string()),
                                           ("ingredient_rules", pa.list_(struct_type(efcy_rule_fields)))])
    grouped, dropped = group_rows(out, item_seqs)
    counts, values = Counter({"dropped_rows": dropped}), {}
    for item_seq, rows in grouped.items():
        entries = []
        for row in rows:
            rule = efcy_rules.get(row["dur_seq"])
            status = LINKED if rule else "연결 안 됨"
            counts[status] += 1
            entries.append({**pick(row, efcy_fields), "link_status": status, "link_method": "규칙 번호",
                            "ingredient_rules": [pick(rule, efcy_rule_fields)] if rule else []})
        values[item_seq] = sorted(entries, key=lambda e: e["dur_seq"])
    caution_values["dur_efficacy_dup"], caution_types["dur_efficacy_dup"] = values, pa.list_(efcy_type)
    link_stats["dur_efficacy_dup"] = dict(counts)

    # 서방정 분할주의 (제품당 1개)
    out, meta, r, _ = prepare(root, DUR_ITEM_SEOBANGJEONG, snapshot)
    rejects += r
    sources[DUR_ITEM_SEOBANGJEONG.name] = meta
    sr_fields = columns_of(DUR_ITEM_SEOBANGJEONG, ["mix_type", "form_code_name", "prohbt_content", "remark",
                                                   "change_date"])
    sr_split = {}
    for row in out.to_pylist():
        if row["item_seq"] in item_seqs:
            sr_split[row["item_seq"]] = pick(row, sr_fields)
        else:
            stats["sr_split_rows_dropped"] += 1

    # 허가 문서
    documents = load_documents(root, snapshot, item_seqs, stats, rejects)
    doc_fields = [("section_idx", pa.int64()), ("section_title", pa.string()), ("article_idx", pa.int64()),
                  ("article_title", pa.string()), ("text", pa.string()), ("content_hash", pa.string())]
    doc_type_columns = {"EE": "doc_efficacy", "UD": "doc_dosage", "NB": "doc_precautions", "PN": "doc_pn"}

    # 조립: 제품 1개 = 1행
    caution_order = ["dur_pregnancy", "dur_elderly", "dur_age", "dur_dosage", "dur_duration", "dur_efficacy_dup"]
    schema = pa.schema(
        [("item_seq", pa.string()), ("sale_status", pa.string())]
        + [(name, kind) for name, kind in base_fields if name != "item_seq"]
        + [("ingredients", pa.list_(struct_type(ingredient_fields))),
           ("pills", pa.list_(struct_type(pill_fields))),
           ("easy_info", struct_type(easy_fields)),
           ("dur_info", struct_type(dur_fields))]
        + [(name, caution_types[name]) for name in caution_order]
        + [("dur_sr_split", struct_type(sr_fields))]
        + [(column, pa.list_(struct_type(doc_fields))) for column in doc_type_columns.values()]
        + [("snapshot", pa.date32())]
    )
    base_rows = {row["item_seq"]: row for row in permit_item.select(base_item_cols).to_pylist() if row["item_seq"] in item_seqs}
    snapshot_date = date.fromisoformat(snapshot)
    rows = []
    for item_seq in sorted(item_seqs):
        row = {"item_seq": item_seq, "sale_status": sale[item_seq], **base_rows[item_seq]}
        row.update({name: detail.get(item_seq, {}).get(name) for name in detail_cols})
        row["ingredients"] = [pick(x, ingredient_fields) for x in
                              sorted(ingredients.get(item_seq, []), key=lambda x: (x["tamt_seq"], x["mtral_sn"]))] or None
        row["pills"] = [pick(x, pill_fields) for x in
                        sorted(pills.get(item_seq, []), key=lambda x: x["image_id"])] or None
        row["easy_info"] = easy.get(item_seq)
        row["dur_info"] = dur_info.get(item_seq)
        in_dur = item_seq in dur_info
        for name in caution_order:
            # DUR 대상 제품은 해당 없음 = 빈 목록, DUR 대상이 아닌 제품은 정보 없음 = null
            row[name] = caution_values[name].get(item_seq, [] if in_dur else None)
        row["dur_sr_split"] = sr_split.get(item_seq)
        docs = documents.get(item_seq, {})
        for doc_type, column in doc_type_columns.items():
            row[column] = docs.get(doc_type)
        row["snapshot"] = snapshot_date
        rows.append(row)
    out = pa.Table.from_pylist(rows, schema=schema)
    validate(out, DRUG_PRODUCT_TABLE, ("item_seq",), ["item_seq", "sale_status", "item_name", "snapshot"])

    missing_detail = sum(1 for s in item_seqs if s not in detail)
    if missing_detail:
        raise BuildError(f"[{DRUG_PRODUCT_TABLE}] 허가 상세가 없는 제품 {missing_detail}개")
    unlinked = {name: s.get("연결 안 됨", 0) for name, s in link_stats.items() if s.get("연결 안 됨")}
    meta = {
        "table": DRUG_PRODUCT_TABLE, "snapshot": snapshot, "spec_version": SPEC_VERSION, "primary_key": ["item_seq"],
        "rows": out.num_rows, "sale_status_counts": dict(Counter(sale.values())),
        "permit_status_mismatch_with_detail": status_mismatch,
        "permit_products_removed": dict(removed), "rows_dropped_from_other_sources": {
            k: v for k, v in stats.items() if k.endswith("_dropped")},
        "dur_link": link_stats, "dur_unlinked": unlinked,
        "documents": {k: v for k, v in stats.items() if k.startswith("doc")},
        "rejected_values": sum(r.get("rows", 1) for r in rejects), "sources": sources,
        "build_seconds": round(time.time() - started),
    }
    return out, meta, rejects


# ---------------------------------------------------------------- 병용금기

def build_contraindication(root, snapshot):
    """성분 병용금기와 품목 병용금기를 한 테이블로. 그 level 에 없는 컬럼은 null 이다 (컬럼 사전의 level 별 컬럼 참고)."""
    ingr, ingr_meta, ingr_rejects, _ = prepare(root, DUR_INGR_USJNT, snapshot)
    item, item_meta, item_rejects, _ = prepare(root, DUR_ITEM_USJNT, snapshot)

    def as_list(column):  # 성분 쪽 이름(문자열)을 품목 쪽처럼 목록으로
        return pa.array([[value] if value else None for value in column.to_pylist()], type=pa.list_(pa.string()))

    # 품목 쪽과 같은 이름은 같은 형식이어야 한다: 성분 이름은 목록으로 통일하고,
    # 성분 규칙의 분류('[코드]이름/…', 복합제는 여러 개)는 품목의 제품 분류(class_code·class_name)와 뜻이 달라 이름을 나눈다
    for single, plural in (("ingr_name", "ingr_names"), ("mixture_ingr_name", "mixture_ingr_names"),
                           ("ingr_eng_name", "ingr_eng_names"), ("mixture_ingr_eng_name", "mixture_ingr_eng_names")):
        ingr = ingr.append_column(plural, as_list(ingr[single])).drop_columns([single])
    ingr = ingr.rename_columns([{"class_name": "rule_class", "class_name_codes": "rule_class_codes",
                                 "mixture_class_name": "mixture_rule_class",
                                 "mixture_class_name_codes": "mixture_rule_class_codes"}.get(n, n)
                                for n in ingr.column_names])
    ingr = ingr.append_column("level", pa.array(["성분"] * ingr.num_rows)).append_column("row_key", ingr["rule_key"])
    item = item.append_column("level", pa.array(["품목"] * item.num_rows)).append_column(
        "row_key", pc.binary_join_element_wise(item["dur_seq"], item["item_seq"], item["mixture_item_seq"], "|"))
    order = ["level", "row_key"]
    for name in ingr.column_names + item.column_names:
        if name not in order and name != "snapshot":
            order.append(name)
    out = pa.concat_tables([ingr, item], promote_options="permissive").select(order + ["snapshot"])
    validate(out, CONTRAINDICATION_TABLE, ("row_key",),
             ["level", "row_key", "ingr_code", "mixture_ingr_code", "type_name", "notification_date", "snapshot"])
    meta = {
        "table": CONTRAINDICATION_TABLE, "snapshot": snapshot, "spec_version": SPEC_VERSION, "primary_key": ["row_key"],
        "rows": out.num_rows, "level_rows": {"성분": ingr.num_rows, "품목": item.num_rows},
        "level_columns": {"성분": [c for c in ingr.column_names if c != "snapshot"],
                          "품목": [c for c in item.column_names if c != "snapshot"]},
        "rejected_values": ingr_meta["rejected_values"] + item_meta["rejected_values"],
        "sources": {DUR_INGR_USJNT.name: ingr_meta, DUR_ITEM_USJNT.name: item_meta},
    }
    return out, meta, ingr_rejects + item_rejects


# ---------------------------------------------------------------- 저장

def table_dir(root, name, snapshot):
    path = root / "silver" / name / f"snapshot={snapshot}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def save(root, snapshot, name, table, meta, rejects):
    """검증을 통과한 테이블만 저장한다."""
    out_dir = table_dir(root, name, snapshot)
    tmp = out_dir / "data.parquet.tmp"
    pq.write_table(table, tmp)
    os.replace(tmp, out_dir / "data.parquet")
    meta["transformed_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(out_dir / "_meta.json", meta)
    rejects_path = out_dir / "_rejects.json"
    if rejects:
        write_json(rejects_path, rejects)
    elif rejects_path.exists():  # 다시 돌렸을 때 이전 실패 기록이 남지 않게
        rejects_path.unlink()


# ---------------------------------------------------------------- 실행

def main():
    parser = argparse.ArgumentParser(description="Bronze → Silver 빌드")
    parser.add_argument("tables", nargs="*", help=f"일부 테이블만 (기본: 전체). 사용 가능: {ALL_TABLE_NAMES}")
    parser.add_argument("--snapshot", help="bronze 스냅샷 날짜 (기본: 모든 원본에 공통인 최신)")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    args = parser.parse_args()
    unknown = [name for name in args.tables if name not in ALL_TABLE_NAMES]
    if unknown:
        raise SystemExit(f"알 수 없는 테이블: {unknown}\n사용 가능: {ALL_TABLE_NAMES}")
    root = Path(args.root)
    selected = set(args.tables or ALL_TABLE_NAMES)
    operations = {PERMIT_ITEM.operation, PERMIT_DETAIL.operation, PERMIT_INGREDIENT.operation, EASY_DRUG.operation,
                  PILL_IDENTIFICATION.operation, DUR_ITEM_MASTER.operation, DUR_ITEM_EFCY_DPLCT.operation,
                  DUR_ITEM_SEOBANGJEONG.operation, *(t.operation for t in DUR_INGR_TABLES),
                  *(t.operation for t in DUR_ITEM_CAUTION_TABLES), *(t.operation for t in OUTPUT_TABLES),
                  DUR_INGR_USJNT.operation, DUR_ITEM_USJNT.operation}
    snapshot = args.snapshot or latest_common_snapshot(root, operations)
    print(f"snapshot={snapshot} spec={SPEC_VERSION} 테이블 {sorted(selected)}", flush=True)

    failures = []
    for table in OUTPUT_TABLES:
        if table.name not in selected:
            continue
        started = time.time()
        try:
            out, meta, rejects, _ = prepare(root, table, snapshot)
            save(root, snapshot, table.name, out, meta, rejects)
            print(f"[{table.name}] {meta['rows']:,}행 (원본 {meta['source_rows']:,}, 중복 {meta['exact_duplicates_removed']}, "
                  f"합침 {meta['collapsed_rows']}, 변환 실패 {meta['rejected_values']}) {time.time() - started:.0f}초", flush=True)
        except BuildError as error:
            failures.append(str(error))
            print(f"실패 {error}", flush=True)
        gc.collect()

    if CONTRAINDICATION_TABLE in selected:
        started = time.time()
        try:
            out, meta, rejects = build_contraindication(root, snapshot)
            save(root, snapshot, CONTRAINDICATION_TABLE, out, meta, rejects)
            print(f"[{CONTRAINDICATION_TABLE}] {meta['rows']:,}행 {meta['level_rows']} {time.time() - started:.0f}초", flush=True)
        except BuildError as error:
            failures.append(str(error))
            print(f"실패 {error}", flush=True)
        gc.collect()

    if DRUG_PRODUCT_TABLE in selected:
        try:
            out, meta, rejects = build_drug_product(root, snapshot)
            save(root, snapshot, DRUG_PRODUCT_TABLE, out, meta, rejects)
            print(f"[{DRUG_PRODUCT_TABLE}] {meta['rows']:,}행 {meta['sale_status_counts']} 제거 {meta['permit_products_removed']} "
                  f"DUR 연결 안 됨 {meta['dur_unlinked'] or 0} {meta['build_seconds']}초", flush=True)
        except BuildError as error:
            failures.append(str(error))
            print(f"실패 {error}", flush=True)

    if failures:
        print(f"\n실패 {len(failures)}건 — _latest.json 을 갱신하지 않음", flush=True)
        sys.exit(1)
    if not args.tables:
        write_json(root / "silver" / "_latest.json", {
            "snapshot": snapshot, "spec_version": SPEC_VERSION, "tables": {name: snapshot for name in ALL_TABLE_NAMES},
            "written_at": datetime.now().isoformat(timespec="seconds"),
        })
        print(f"_latest.json → {snapshot}", flush=True)


if __name__ == "__main__":
    main()

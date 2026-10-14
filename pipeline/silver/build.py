"""Bronze → Silver 빌드 (명세: docs/silver_table_spec.md, 코드 명세: tables.py).

  python pipeline/silver/build.py                          # 모든 오퍼레이션에 공통인 최신 스냅샷으로 전체 빌드
  python pipeline/silver/build.py --snapshot 2026-10-13
  python pipeline/silver/build.py easy_drug dur_ingr_usjnt # 일부만 다시 만들기 (_latest.json 은 건드리지 않음)

출력: {root}/silver/{table}/snapshot={날짜}/data.parquet, _meta.json
      {root}/silver/_rejects/snapshot={날짜}/{table}.json
      {root}/silver/_latest.json  ← 전체 빌드가 모두 검증을 통과했을 때만 마지막에 갱신
"""

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from tables import (
    ALL_TABLE_NAMES, DOC_SOURCE_COLUMNS, DOC_TABLES, EASY_DRUG, EASY_TEXT_FIELDS, EASY_TEXT_TABLE, PERMIT_DETAIL,
    SPEC_VERSION, TABLES,
)

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "s3"
PLACEHOLDER_NULL = {"PROHBT_CONTENT": {"-", "_"}}  # 내용 없음을 뜻하는 자리표시 값
ARROW_TYPES = {
    "str": pa.string(), "int": pa.int64(), "float": pa.float64(), "date": pa.date32(), "bool": pa.bool_(),
    "list": pa.list_(pa.string()),
}
DERIVED_SOURCES = {"is_active": ("CANCEL_NAME",), "is_rule_valid": ("DEL_YN",),
                   "pair_key": ("INGR_CODE", "MIXTURE_INGR_CODE")}
BATCH_ROWS = 200_000
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


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


def complete_pages(root, operation, snapshot):
    """스냅샷의 페이지 경로 목록과 totalCount. 페이지가 빠졌으면 실패."""
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
    total = int(first["response"]["body"]["totalCount"])
    expected = set(range(1, math.ceil(total / first["meta"]["num_of_rows"]) + 1))
    if set(pages) != expected:
        raise BuildError(f"[{operation}] 페이지 불일치: 없음 {sorted(expected - set(pages))[:10]}, "
                         f"남음 {sorted(set(pages) - expected)[:10]}")
    return [pages[n] for n in sorted(pages)], total


def iter_pages(root, operation, snapshot):
    """페이지마다 항목 목록(컬럼명 앞뒤 공백 제거)을 돌려주고, 끝나면 건수를 totalCount 와 대조한다."""
    paths, total = complete_pages(root, operation, snapshot)
    count = 0
    for path in paths:
        items = unwrap_items(json.loads(path.read_text(encoding="utf-8"))["response"]["body"])
        count += len(items)
        yield [{name.strip(): value for name, value in item.items()} for item in items]
    if count != total:
        raise BuildError(f"[{operation}] 항목 수 {count} != totalCount {total}")


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
        raise BuildError("모든 오퍼레이션에 공통인 bronze 스냅샷이 없음")
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


# ---------------------------------------------------------------- 행 처리

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
    """원본 테이블 → silver 테이블. (결과, 메타, rejects, 합친 뒤 원본 형태 테이블)"""
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


def build_easy_text(easy, snapshot):
    """e약은요 7문항 → (item_seq, field) 세로 형태. 본문이 null 인 문항은 행을 만들지 않는다."""
    rows = {"item_seq": [], "field": [], "text": [], "content_hash": []}
    item_seqs = easy["itemSeq"].to_pylist()
    for source, field in EASY_TEXT_FIELDS.items():
        for item_seq, text in zip(item_seqs, easy[source].to_pylist()):
            if text is not None:
                rows["item_seq"].append(item_seq)
                rows["field"].append(field)
                rows["text"].append(text)
                rows["content_hash"].append(stable_hash([field, text]))
    out = pa.table(rows, schema=pa.schema([(name, pa.string()) for name in rows]))
    out = out.append_column("snapshot", pa.array([date.fromisoformat(snapshot)] * out.num_rows, type=pa.date32()))
    out = out.sort_by([("item_seq", "ascending"), ("field", "ascending")])
    validate(out, EASY_TEXT_TABLE, ("item_seq", "field"), list(out.column_names))
    meta = {
        "table": EASY_TEXT_TABLE, "source_operation": EASY_DRUG.operation, "snapshot": snapshot,
        "spec_version": SPEC_VERSION, "primary_key": ["item_seq", "field"], "source_items": easy.num_rows,
        "rows": out.num_rows, "distinct_texts": len(set(rows["content_hash"])),
    }
    return out, meta


# ---------------------------------------------------------------- 허가 문서 텍스트

def strip_html(text):
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)  # 태그만 지운다 ('pH < 7' 같은 본문은 건드리지 않음)
    return html.unescape(text).strip() or None


def parse_doc(xml_text):
    """문서 XML → [(섹션 번호, 섹션 제목, 항목 번호, 항목 제목, [(문단 번호, 태그, 본문)])], 구조 밖 문단 수."""
    root = ET.fromstring(xml_text)
    articles, inside = [], 0
    for section_idx, section in enumerate(root.iter("SECTION"), start=1):
        for article_idx, article in enumerate(section.findall("ARTICLE"), start=1):
            paragraphs = []
            for paragraph_idx, paragraph in enumerate(article.findall("PARAGRAPH"), start=1):
                inside += 1
                paragraphs.append((paragraph_idx, clean("", paragraph.get("tagName")), strip_html(paragraph.text or "")))
            articles.append((section_idx, clean("", section.get("title")), article_idx,
                             clean("", article.get("title")), paragraphs))
    return articles, len(list(root.iter("PARAGRAPH"))) - inside


ARTICLE_SCHEMA = pa.schema([("item_seq", pa.string()), ("doc_type", pa.string()), ("section_idx", pa.int64()),
                            ("article_idx", pa.int64()), ("content_hash", pa.string())])
PARAGRAPH_SCHEMA = pa.schema(list(ARTICLE_SCHEMA)[:4] + [("paragraph_idx", pa.int64()), ("content_hash", pa.string())])
ARTICLE_TEXT_SCHEMA = pa.schema([("content_hash", pa.string()), ("doc_type", pa.string()),
                                 ("section_title", pa.string()), ("article_title", pa.string()), ("text", pa.string())])
PARAGRAPH_TEXT_SCHEMA = pa.schema(list(ARTICLE_TEXT_SCHEMA)[:4] + [("paragraph_tag", pa.string()),
                                                                     ("text", pa.string())])


def with_snapshot(t, snapshot):
    return t.append_column("snapshot", pa.array([date.fromisoformat(snapshot)] * t.num_rows, type=pa.date32()))


def build_doc_tables(root, snapshot):
    """허가 상세의 문서 XML → 고유 텍스트 테이블 2개 + 제품 연결 테이블 2개. 문단 연결(400만 행)은 배치로 쓴다."""
    article_texts, paragraph_texts = {}, {}
    article_rows = {name: [] for name in ARTICLE_SCHEMA.names}
    paragraph_rows = {name: [] for name in PARAGRAPH_SCHEMA.names}
    stats = {"items": 0, "documents": 0, "parse_failures": 0, "paragraphs_outside_structure": 0,
             "empty_paragraphs": 0, "paragraph_rows": 0}
    rejects, seen_items = [], set()
    paragraph_dir = table_dir(root, "doc_paragraph", snapshot)
    paragraph_tmp = paragraph_dir / "data.parquet.tmp"
    writer = pq.ParquetWriter(paragraph_tmp, PARAGRAPH_SCHEMA.append(pa.field("snapshot", pa.date32())))

    def flush_paragraphs():
        if paragraph_rows["item_seq"]:
            batch = pa.table(paragraph_rows, schema=PARAGRAPH_SCHEMA)
            writer.write_table(with_snapshot(batch, snapshot))
            stats["paragraph_rows"] += batch.num_rows
            for values in paragraph_rows.values():
                values.clear()

    try:
        for items in iter_pages(root, PERMIT_DETAIL.operation, snapshot):
            for item in items:
                item_seq = clean("ITEM_SEQ", item.get("ITEM_SEQ"))
                if item_seq is None or item_seq in seen_items:
                    raise BuildError(f"[doc] ITEM_SEQ 가 비었거나 중복: {item_seq}")
                seen_items.add(item_seq)
                stats["items"] += 1
                for source, doc_type in DOC_SOURCE_COLUMNS.items():
                    xml_text = clean(source, item.get(source))
                    if xml_text is None:
                        continue
                    stats["documents"] += 1
                    try:
                        articles, outside = parse_doc(xml_text)
                    except ET.ParseError:
                        stats["parse_failures"] += 1
                        rejects.append({"item_seq": item_seq, "column": source, "raw_value": "XML 파싱 실패"})
                        continue
                    stats["paragraphs_outside_structure"] += outside
                    for section_idx, section_title, article_idx, article_title, paragraphs in articles:
                        body = "\n".join(text for _, _, text in paragraphs if text) or None
                        article_hash = stable_hash([doc_type, section_title, article_title, body])
                        article_texts.setdefault(article_hash, (doc_type, section_title, article_title, body))
                        for name, value in zip(ARTICLE_SCHEMA.names,
                                               (item_seq, doc_type, section_idx, article_idx, article_hash)):
                            article_rows[name].append(value)
                        for paragraph_idx, tag, text in paragraphs:
                            if text is None:
                                stats["empty_paragraphs"] += 1
                                continue
                            paragraph_hash = stable_hash([doc_type, section_title, article_title, tag, text])
                            paragraph_texts.setdefault(paragraph_hash,
                                                       (doc_type, section_title, article_title, tag, text))
                            for name, value in zip(PARAGRAPH_SCHEMA.names, (item_seq, doc_type, section_idx,
                                                                            article_idx, paragraph_idx,
                                                                            paragraph_hash)):
                                paragraph_rows[name].append(value)
                            if len(paragraph_rows["item_seq"]) >= BATCH_ROWS:
                                flush_paragraphs()
        flush_paragraphs()
    finally:
        writer.close()

    outputs = {}
    article = with_snapshot(pa.table(article_rows, schema=ARTICLE_SCHEMA), snapshot)
    validate(article, "doc_article", ARTICLE_SCHEMA.names[:4], article.column_names)
    outputs["doc_article"] = article
    for name, texts, schema in (("doc_article_text", article_texts, ARTICLE_TEXT_SCHEMA),
                                ("doc_paragraph_text", paragraph_texts, PARAGRAPH_TEXT_SCHEMA)):
        hashes = sorted(texts)
        columns = {"content_hash": hashes}
        for i, field in enumerate(schema.names[1:]):
            columns[field] = [texts[h][i] for h in hashes]
        out = with_snapshot(pa.table(columns, schema=schema), snapshot)
        validate(out, name, ("content_hash",), ["content_hash", "doc_type", "snapshot"])
        outputs[name] = out
    paragraph_keys = pq.read_table(paragraph_tmp, columns=PARAGRAPH_SCHEMA.names[:5])
    validate(paragraph_keys, "doc_paragraph", PARAGRAPH_SCHEMA.names[:5], PARAGRAPH_SCHEMA.names[:5])

    common = {"source_operation": PERMIT_DETAIL.operation, "snapshot": snapshot, "spec_version": SPEC_VERSION,
              **stats}
    metas = {
        "doc_article": {"primary_key": ARTICLE_SCHEMA.names[:4], "rows": article.num_rows},
        "doc_paragraph": {"primary_key": PARAGRAPH_SCHEMA.names[:5], "rows": stats["paragraph_rows"]},
        "doc_article_text": {"primary_key": ["content_hash"], "rows": outputs["doc_article_text"].num_rows},
        "doc_paragraph_text": {"primary_key": ["content_hash"], "rows": outputs["doc_paragraph_text"].num_rows},
    }
    for name in DOC_TABLES:
        meta = {"table": name, **common, **metas[name]}
        if name == "doc_paragraph":
            os.replace(paragraph_tmp, paragraph_dir / "data.parquet")
            save(root, snapshot, name, None, meta, rejects)
        else:
            save(root, snapshot, name, outputs[name], meta, rejects)
    return metas, stats


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
    """검증을 통과한 테이블만 저장한다. table 이 None 이면 data.parquet 은 이미 써 둔 것."""
    out_dir = table_dir(root, name, snapshot)
    if table is not None:
        tmp = out_dir / "data.parquet.tmp"
        pq.write_table(table, tmp)
        os.replace(tmp, out_dir / "data.parquet")
    meta["transformed_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(out_dir / "_meta.json", meta)
    rejects_dir = root / "silver" / "_rejects" / f"snapshot={snapshot}"
    rejects_dir.mkdir(parents=True, exist_ok=True)
    write_json(rejects_dir / f"{name}.json", rejects)  # 실패가 없어도 빈 목록으로 덮어쓴다


# ---------------------------------------------------------------- 실행

def main():
    parser = argparse.ArgumentParser(description="Bronze → Silver 빌드")
    parser.add_argument("tables", nargs="*", help=f"일부 테이블만 (기본: 전체). 사용 가능: {ALL_TABLE_NAMES}")
    parser.add_argument("--snapshot", help="bronze 스냅샷 날짜 (기본: 모든 오퍼레이션에 공통인 최신)")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    args = parser.parse_args()
    unknown = [name for name in args.tables if name not in ALL_TABLE_NAMES]
    if unknown:
        raise SystemExit(f"알 수 없는 테이블: {unknown}\n사용 가능: {ALL_TABLE_NAMES}")
    root = Path(args.root)
    selected = set(args.tables or ALL_TABLE_NAMES)
    snapshot = args.snapshot or latest_common_snapshot(root, {t.operation for t in TABLES})
    print(f"snapshot={snapshot} spec={SPEC_VERSION} 테이블 {len(selected)}개", flush=True)

    failures = []
    for table in TABLES:
        with_easy_text = table is EASY_DRUG and EASY_TEXT_TABLE in selected
        if table.name not in selected and not with_easy_text:
            continue
        started = time.time()
        try:
            skip = tuple(DOC_SOURCE_COLUMNS) if table is PERMIT_DETAIL else ()
            out, meta, rejects, prepared = build_table(table, load_source(root, table.operation, snapshot, skip), snapshot)
            if table.name in selected:
                save(root, snapshot, table.name, out, meta, rejects)
                warn = f" 원본에만 있는 컬럼 {meta['unmapped_source_columns']}" if meta["unmapped_source_columns"] else ""
                print(f"[{table.name}] {meta['rows']:,}행 (원본 {meta['source_rows']:,}, 중복 "
                      f"{meta['exact_duplicates_removed']}, 합침 {meta['collapsed_rows']}, 제외 {meta['excluded_rows']}, "
                      f"변환 실패 {meta['rejected_values']}) {time.time() - started:.0f}초{warn}", flush=True)
            if with_easy_text:
                text, text_meta = build_easy_text(prepared, snapshot)
                save(root, snapshot, EASY_TEXT_TABLE, text, text_meta, [])
                print(f"[{EASY_TEXT_TABLE}] {text_meta['rows']:,}행 (고유 텍스트 {text_meta['distinct_texts']:,})",
                      flush=True)
        except BuildError as error:
            failures.append(str(error))
            print(f"실패 {error}", flush=True)

    if selected & set(DOC_TABLES):
        started = time.time()
        try:
            metas, stats = build_doc_tables(root, snapshot)
            print(f"[doc] " + ", ".join(f"{name} {m['rows']:,}행" for name, m in metas.items())
                  + f" {stats} {time.time() - started:.0f}초", flush=True)
        except BuildError as error:
            failures.append(str(error))
            print(f"실패 {error}", flush=True)

    if failures:
        print(f"\n실패 {len(failures)}건 — _latest.json 을 갱신하지 않음", flush=True)
        sys.exit(1)
    if not args.tables:
        write_json(root / "silver" / "_latest.json", {
            "snapshot": snapshot, "spec_version": SPEC_VERSION, "tables": ALL_TABLE_NAMES,
            "written_at": datetime.now().isoformat(timespec="seconds"),
        })
        print(f"_latest.json → {snapshot}", flush=True)


if __name__ == "__main__":
    main()

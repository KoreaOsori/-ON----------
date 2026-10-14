"""변환된 silver 에서 컬럼 사전(docs/silver_columns.md)을 만든다.

_latest.json 의 스냅샷을 읽는다. 스키마와 통계는 Parquet 에서 읽으므로 명세와 실제가 다르면 이 문서가 실제를 보여 준다.
"""

import argparse
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from tables import ALL_TABLE_NAMES, TABLES

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "s3"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "docs" / "silver_columns.md"
SPEC_COLUMNS = {t.name: {c.name: c for c in t.columns} for t in TABLES}

INTRO = """# Silver 컬럼 사전

> `pipeline/silver/describe.py`가 변환된 Parquet에서 자동 생성한 문서다. 직접 고치지 않는다.
> 설계 규칙은 [silver_table_spec.md](silver_table_spec.md), 결정 배경은 [silver_decisions.md](silver_decisions.md).

## 읽는 법

- 경로: `silver/{{table}}/snapshot=YYYY-MM-DD/data.parquet`. 항상 `silver/_latest.json`에 적힌 스냅샷만 읽는다 (검증을 통과한 버전).
- 서비스 대상 약 필터: `permit_item.is_active` (허가 상태가 "정상"). 텍스트 테이블은 연결 테이블(`doc_article`, `doc_paragraph`)에서 이 플래그와 조인해서 거른다.
- DUR 성분 규칙의 유효 여부: `is_rule_valid` (`del_yn`이 "정상").
- 허가 문서 텍스트: `doc_*_text`는 고유 텍스트(중복 제거됨), `doc_article` / `doc_paragraph`는 제품 → 텍스트 연결. 제품별 원래 형태가 필요하면 `content_hash`로 조인한다.
- `content_hash`, `rule_key`는 내용으로 만든 해시라 내용이 같으면 스냅샷이 바뀌어도 같다. 변경 감지에 쓴다.
- 숫자로 바꾸지 못한 원본 값은 null이고, 원래 값은 `silver/_rejects/snapshot=YYYY-MM-DD/{{table}}.json`에 있다.
- 값이 null인 것은 "원본에 정보 없음"이다. "해당 없음"으로 해석하지 않는다.

스냅샷: **{snapshot}** · 명세 버전: {spec_version}
"""


def sample_text(value, limit=40):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", "\\n").replace("|", "\\|")
    return text if len(text) <= limit else text[:limit] + "…"


def describe_table(name, table_dir):
    parquet = pq.ParquetFile(table_dir / "data.parquet")
    meta = json.loads((table_dir / "_meta.json").read_text(encoding="utf-8"))
    rows = parquet.metadata.num_rows
    spec = SPEC_COLUMNS.get(name, {})
    lines = [f"## {name}", "", f"원본 `{meta['source_operation']}` · **{rows:,}행** · PK `({', '.join(meta['primary_key'])})`"]
    notes = []
    for key, label in (("exact_duplicates_removed", "완전 중복 제거"), ("collapsed_rows", "합친 행"),
                       ("excluded_rows", "제외"), ("rejected_values", "변환 실패 값")):
        if meta.get(key):
            notes.append(f"{label} {meta[key]:,}")
    if meta.get("excluded_reason"):
        notes.append(f"제외 사유: {meta['excluded_reason']}")
    if meta.get("distinct_texts"):
        notes.append(f"고유 텍스트 {meta['distinct_texts']:,}")
    if notes:
        lines.append(" · ".join(notes))
    lines += ["", "| 컬럼 | 타입 | 필수 | null 비율 | 원본 컬럼 | 샘플 |", "| --- | --- | --- | --- | --- | --- |"]
    for field in parquet.schema_arrow:
        column = parquet.read(columns=[field.name]).column(0)
        present = pc.drop_null(column)
        sample = sample_text(present[0].as_py()) if len(present) else "-"
        col = spec.get(field.name)
        required = "O" if (col and col.required) or field.name in ("snapshot", *meta["primary_key"]) else ""
        source = f"`{col.src}`" if col and col.src else ("파생" if col else "")
        null_ratio = column.null_count / rows if rows else 0
        lines.append(f"| `{field.name}` | {field.type} | {required} | {null_ratio:.1%} | {source} | {sample} |")
    lines.append("")
    return lines


def main():
    parser = argparse.ArgumentParser(description="silver 컬럼 사전 생성")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    silver = Path(args.root) / "silver"
    latest = json.loads((silver / "_latest.json").read_text(encoding="utf-8"))
    snapshot = latest["snapshot"]
    dirs = {name: silver / name / f"snapshot={snapshot}" for name in ALL_TABLE_NAMES}

    lines = [INTRO.format(snapshot=snapshot, spec_version=latest["spec_version"]),
             "| 테이블 | 행 수 | PK |", "| --- | --- | --- |"]
    for name, table_dir in dirs.items():
        meta = json.loads((table_dir / "_meta.json").read_text(encoding="utf-8"))
        lines.append(f"| [{name}](#{name}) | {meta['rows']:,} | `{', '.join(meta['primary_key'])}` |")
    lines.append("")
    for name, table_dir in dirs.items():
        lines += describe_table(name, table_dir)
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(dirs)}개 테이블 → {args.out}")


if __name__ == "__main__":
    main()

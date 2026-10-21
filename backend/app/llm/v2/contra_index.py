"""병용금기(DUR) parquet → 읽기 전용 SQLite 인덱스 변환.

    python -m app.llm.v2.contra_index --parquet data/contraindication/data.parquet --out dev_data/contraindication.sqlite

- 원본(`data/contraindication/data.parquet`)은 80만 행이다: 성분 규칙(level='성분') 1,832행 + 제품 쌍 규칙(level='품목') 약 80만 행.
  제품 쌍 행은 (item_seq, mixture_item_seq) = (제품 A, 제품 B) 이고 양방향이 모두 들어 있다.
  item_seq(품목기준코드)는 검색 DB 의 product_key 'drug:<item_seq>' 와 같은 값이라 서로 연결된다.
- 런타임이 pyarrow 를 요구하지 않도록, 변환은 한 번만 하고 결과는 표준 라이브러리 sqlite3 로 읽는다.
  (pyarrow 는 이 변환 때만 필요하다: vector_pipeline 의 가상환경에 있다.)
- 방향은 (작은 코드, 큰 코드)로 한 번만 저장하고, 규칙 본문은 중복을 합쳐 rules 에 한 번만 둔다.
- 이 파일은 DB(RDS)나 vector_pipeline 을 건드리지 않는다. 출력은 로컬 파일 하나다(.gitignore 대상 dev_data/).
"""
import argparse
import os
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

PAIR_LEVEL = "품목"
PARQUET_COLUMNS = (
    "level", "item_seq", "mixture_item_seq", "ingr_names", "mixture_ingr_names", "prohbt_content",
    "remark", "form_name", "notification_date", "dur_seq", "snapshot",
)

SCHEMA_SQL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE rules (
    id INTEGER PRIMARY KEY,
    dur_seq TEXT,
    first_names TEXT NOT NULL,   -- 작은 코드 쪽 제품의 성분
    second_names TEXT NOT NULL,  -- 큰 코드 쪽 제품의 성분
    content TEXT NOT NULL,       -- 금기 내용(원문)
    remark TEXT,                 -- 조건·비고(원문)
    form_name TEXT,
    notified TEXT                -- 고시일 YYYY-MM-DD
);
CREATE TABLE pairs (
    a TEXT NOT NULL,             -- 작은 item_seq
    b TEXT NOT NULL,             -- 큰 item_seq
    rule_id INTEGER NOT NULL REFERENCES rules(id),
    PRIMARY KEY (a, b, rule_id)
) WITHOUT ROWID;
CREATE INDEX pairs_by_b ON pairs (b);
"""


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _names(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    return ", ".join(str(v).strip() for v in value if str(v).strip())


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def build_index(rows: Iterable[dict[str, Any]], out_path: str | Path) -> dict[str, Any]:
    """rows(원본 컬럼 이름의 dict)에서 제품 쌍 규칙만 골라 SQLite 파일을 만든다. 통계를 돌려준다."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(suffix=".sqlite.tmp", dir=str(out_path.parent))
    os.close(handle)
    stats = {"rows_read": 0, "pair_rows": 0, "rules": 0, "pairs": 0, "snapshot": None}
    connection = sqlite3.connect(tmp_name)
    try:
        connection.executescript(SCHEMA_SQL)
        rule_ids: dict[tuple, int] = {}
        pair_batch: set[tuple[str, str, int]] = set()
        for row in rows:
            stats["rows_read"] += 1
            if stats["snapshot"] is None and row.get("snapshot") is not None:
                stats["snapshot"] = _iso(row["snapshot"])
            if row.get("level") != PAIR_LEVEL:
                continue
            first, second = _text(row.get("item_seq")), _text(row.get("mixture_item_seq"))
            content = _text(row.get("prohbt_content"))
            if not first or not second or first == second or not content:
                continue
            stats["pair_rows"] += 1
            first_names, second_names = _names(row.get("ingr_names")), _names(row.get("mixture_ingr_names"))
            if first > second:  # 항상 (작은 코드, 큰 코드) 방향으로 저장한다
                first, second, first_names, second_names = second, first, second_names, first_names
            rule = (
                _text(row.get("dur_seq")), first_names, second_names, content, _text(row.get("remark")),
                _text(row.get("form_name")), _iso(row.get("notification_date")),
            )
            rule_id = rule_ids.get(rule)
            if rule_id is None:
                rule_id = rule_ids[rule] = len(rule_ids) + 1
                connection.execute("INSERT INTO rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (rule_id, *rule))
            pair_batch.add((first, second, rule_id))
            if len(pair_batch) >= 50_000:
                connection.executemany("INSERT OR IGNORE INTO pairs VALUES (?, ?, ?)", pair_batch)
                pair_batch.clear()
        if pair_batch:
            connection.executemany("INSERT OR IGNORE INTO pairs VALUES (?, ?, ?)", pair_batch)
        stats["rules"] = len(rule_ids)
        stats["pairs"] = connection.execute("SELECT COUNT(*) FROM pairs").fetchone()[0]
        for key, value in (
            ("snapshot", stats["snapshot"] or ""), ("rules", str(stats["rules"])), ("pairs", str(stats["pairs"])),
            ("source", "data/contraindication/data.parquet (level=품목)"),
        ):
            connection.execute("INSERT INTO meta VALUES (?, ?)", (key, value))
        connection.commit()
    except BaseException:
        connection.close()
        try:
            os.unlink(tmp_name)
        except OSError:  # 삭제가 막힌 폴더 등: 임시 파일이 남을 수 있다(원래 오류를 가리지 않는다)
            pass
        raise
    connection.close()
    os.replace(tmp_name, out_path)
    return stats


def iter_parquet_rows(path: str | Path, batch_size: int = 50_000) -> Iterator[dict[str, Any]]:
    """parquet 을 행(dict) 단위로 읽는다. pyarrow 가 필요하다(이 함수를 부를 때만 import)."""
    import pyarrow.parquet as pq  # 지연 import: 런타임/테스트는 pyarrow 없이 동작한다

    parquet = pq.ParquetFile(str(path))
    columns = [c for c in PARQUET_COLUMNS if c in parquet.schema_arrow.names]
    for batch in parquet.iter_batches(batch_size=batch_size, columns=columns):
        yield from batch.to_pylist()


def main() -> None:
    parser = argparse.ArgumentParser(description="병용금기 parquet → SQLite 인덱스")
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args()
    stats = build_index(iter_parquet_rows(arguments.parquet), arguments.out)
    print(
        f"읽은 행 {stats['rows_read']:,} · 제품 쌍 행 {stats['pair_rows']:,} → 규칙 {stats['rules']:,}개, "
        f"제품 쌍 {stats['pairs']:,}개 · 자료 기준일 {stats['snapshot']} → {arguments.out}"
    )


if __name__ == "__main__":
    main()

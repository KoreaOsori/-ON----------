"""병용금기 인덱스(SQLite) 읽기. 표준 라이브러리만 사용하고, 파일은 읽기 전용으로 연다.

contra_index.py 가 만든 파일을 조회한다. 키는 item_seq(품목기준코드) 문자열이며, 검색 DB 의 product_key 'drug:<item_seq>' 에서
접두어를 뗀 값이다. 모든 값은 파라미터로 바인딩한다.
"""
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path


class ContraStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContraRule:
    first_names: str   # 질문에서 앞에 놓은 제품 쪽 성분
    second_names: str
    content: str       # 금기 내용(원문)
    remark: str | None  # 조건·비고(원문)
    form_name: str | None
    notified: str | None  # 고시일 YYYY-MM-DD
    dur_seq: str | None = None


@dataclass(frozen=True)
class PairCheck:
    first: str
    second: str
    rules: list[ContraRule]


@dataclass(frozen=True)
class LookupResult:
    pairs: list[PairCheck]
    has_rules: dict[str, bool]  # 각 제품이 이 자료에 규칙을 하나라도 가지는가


class ContraStore:
    """읽기 전용 SQLite. 호출마다 짧게 연결을 열고 닫는다(스레드 안전, 별도 풀 불필요)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise ContraStoreError("병용금기 인덱스 파일이 없습니다.")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{self._path.resolve().as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        return connection

    def meta(self, key: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def lookup(self, seqs: list[str], max_rules_per_pair: int = 20) -> LookupResult:
        """seqs 의 모든 조합(앞→뒤 순서)에 대한 규칙과, 제품별 규칙 보유 여부."""
        pairs: list[PairCheck] = []
        has_rules: dict[str, bool] = {}
        with closing(self._connect()) as connection:
            for seq in seqs:
                row = connection.execute("SELECT 1 FROM pairs WHERE a = ? OR b = ? LIMIT 1", (seq, seq)).fetchone()
                has_rules[seq] = row is not None
            for first, second in combinations(seqs, 2):
                small, large = (first, second) if first <= second else (second, first)
                rows = connection.execute(
                    "SELECT r.first_names, r.second_names, r.content, r.remark, r.form_name, r.notified, r.dur_seq "
                    "FROM pairs p JOIN rules r ON r.id = p.rule_id WHERE p.a = ? AND p.b = ? ORDER BY r.id LIMIT ?",
                    (small, large, max_rules_per_pair),
                ).fetchall()
                swapped = first > second  # 저장 방향과 질문 방향이 다르면 성분 쪽도 맞바꾼다
                rules = [
                    ContraRule(
                        first_names=(row[1] if swapped else row[0]),
                        second_names=(row[0] if swapped else row[1]),
                        content=row[2], remark=row[3], form_name=row[4], notified=row[5], dur_seq=row[6],
                    )
                    for row in rows
                ]
                pairs.append(PairCheck(first, second, rules))
        return LookupResult(pairs, has_rules)

    def pairs_among(self, seqs: list[str], limit: int = 200) -> list[tuple[str, str]]:
        """seqs 안에서 서로 규칙이 있는 제품 쌍(평가용). 점검 규모가 작을 때만 쓴다."""
        seqs = list(dict.fromkeys(seqs))[:1000]
        if len(seqs) < 2:
            return []
        marks = ",".join("?" * len(seqs))
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT DISTINCT a, b FROM pairs WHERE a IN ({marks}) AND b IN ({marks}) ORDER BY a, b LIMIT ?",
                (*seqs, *seqs, limit),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

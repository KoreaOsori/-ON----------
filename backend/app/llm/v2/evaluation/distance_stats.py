"""거리 분포 요약과 임계값(LLM_V2_MAX_DISTANCE) 후보 표. 표준 라이브러리만 사용, DB/AWS 호출 없음.

임계값은 '정답 근거는 통과시키고 무관한 근거는 막는' 값이어야 한다.
- 정답 근거의 거리(correct): 질문에 맞는 제품·섹션이 검색됐을 때의 코사인 거리. 못 찾은 케이스는 None.
- 무관 질문의 1등 거리(unrelated): 약과 상관없는 질문을 해도 제품 범위 안에서 가장 가까운 문단의 거리.
  이 값이 임계값보다 작으면 무관한 문단이 모델에 들어간다.
"""
import math
from dataclasses import dataclass
from statistics import median


def percentile(sorted_values: list[float], fraction: float) -> float:
    """nearest-rank 백분위. sorted_values 는 오름차순이고 비어 있지 않아야 한다."""
    if not sorted_values:
        raise ValueError("값이 없습니다.")
    index = max(0, math.ceil(fraction * len(sorted_values)) - 1)
    return sorted_values[index]


def distance_stats(values: list[float | None]) -> dict[str, float | int | None]:
    """count(찾은 수), missing(None 수), min, median, p90, max. 값이 없으면 통계는 None."""
    found = sorted(v for v in values if v is not None)
    missing = len(values) - len(found)
    if not found:
        return {"count": 0, "missing": missing, "min": None, "median": None, "p90": None, "max": None}
    return {
        "count": len(found),
        "missing": missing,
        "min": found[0],
        "median": median(found),
        "p90": percentile(found, 0.9),
        "max": found[-1],
    }


def format_stats(label: str, stats: dict[str, float | int | None]) -> str:
    if not stats["count"]:
        return f"{label}: 값 없음 (못 찾음 {stats['missing']}건)"
    return (
        f"{label}: n={stats['count']} (못 찾음 {stats['missing']}) | "
        f"최소 {stats['min']:.3f} · 중앙값 {stats['median']:.3f} · 90% {stats['p90']:.3f} · 최대 {stats['max']:.3f}"
    )


@dataclass(frozen=True)
class ThresholdRow:
    threshold: float
    kept: float     # 정답 근거 중 임계값 이하(= 모델에 전달됨)인 비율. 못 찾은 케이스는 분모에 포함, 분자에서 제외
    blocked: float  # 무관 질문 중 1등도 임계값 초과(= 모델에 전달되지 않음)인 비율

    @property
    def score(self) -> float:
        return self.kept + self.blocked


def default_grid(start: float = 0.40, stop: float = 1.20, step: float = 0.05) -> list[float]:
    count = int(round((stop - start) / step))
    return [round(start + step * i, 4) for i in range(count + 1)]


def threshold_table(
    correct: list[float | None], unrelated: list[float], grid: list[float] | None = None
) -> list[ThresholdRow]:
    """임계값 후보별로 '정답 통과율'과 '무관 차단율'을 계산한다."""
    if not correct or not unrelated:
        return []
    rows = []
    for threshold in grid or default_grid():
        kept = sum(1 for d in correct if d is not None and d <= threshold) / len(correct)
        blocked = sum(1 for d in unrelated if d > threshold) / len(unrelated)
        rows.append(ThresholdRow(threshold, kept, blocked))
    return rows


def suggest_threshold(rows: list[ThresholdRow]) -> ThresholdRow | None:
    """통과율+차단율이 가장 큰 행. 같으면 정답을 덜 놓치는(= 임계값이 큰) 쪽."""
    if not rows:
        return None
    return max(rows, key=lambda row: (round(row.score, 9), row.threshold))


def format_table(rows: list[ThresholdRow], suggested: ThresholdRow | None) -> str:
    lines = ["임계값 | 정답 통과 | 무관 차단"]
    for row in rows:
        mark = "  ← 추천 후보" if suggested is not None and row.threshold == suggested.threshold else ""
        lines.append(f"{row.threshold:>6.2f} | {row.kept:>8.1%} | {row.blocked:>8.1%}{mark}")
    return "\n".join(lines)


def overlap_warning(correct: list[float | None], unrelated: list[float]) -> str | None:
    """두 분포가 겹치면(정답의 최대 거리 >= 무관의 최소 거리) 임계값 하나로 완전히 나눌 수 없다."""
    found = [d for d in correct if d is not None]
    if not found or not unrelated:
        return None
    if max(found) >= min(unrelated):
        return (
            f"주의: 정답 근거의 최대 거리({max(found):.3f})가 무관 질문의 최소 거리({min(unrelated):.3f}) 이상입니다. "
            "임계값 하나로 둘을 완전히 나눌 수 없으니, 정답을 놓치는 쪽과 무관 문단이 들어가는 쪽 중 어느 위험을 더 줄일지 정해야 합니다."
        )
    return None

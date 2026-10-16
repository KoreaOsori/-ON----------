"""수집 → bronze 검증 → silver 빌드를 한 번에 실행한다. 스케줄러는 이 스크립트만 부르면 된다.

  python pipeline/run_pipeline.py                          # 오늘 날짜 스냅샷
  python pipeline/run_pipeline.py --snapshot 2026-10-14    # 중간에 끊긴 수집 이어받기 (같은 날짜로 다시 실행)

1. 수집: 등록된 API 전부 (이미 받은 페이지는 건너뜀)
2. bronze 검증: API 마다 _manifest.json 기준으로 받은 건수 = 전체 건수, 빠진 페이지 0, 실패한 페이지 0
3. 하나라도 실패하면 silver 를 만들지 않고 종료 코드 1
4. 통과하면 같은 날짜로 silver 빌드 (silver 검증에 실패하면 _latest.json 은 바뀌지 않음)
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR / "collect"))

from collect import (  # noqa: E402
    ALL_OPERATIONS, DEFAULT_OUT, DEFAULT_ROWS, FOOD_SAFETY_ROWS, collect_operation, get_service_key, is_food_safety,
)


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def collect_all(snapshot, root):
    """API 마다 수집. 한 API 가 실패해도 나머지는 계속 받는다."""
    errors = {}
    for operation in ALL_OPERATIONS:
        rows = FOOD_SAFETY_ROWS if is_food_safety(operation) else DEFAULT_ROWS
        try:
            collect_operation(operation, snapshot, root, rows, get_service_key(operation))
        except (SystemExit, Exception) as error:  # 1쪽 실패, 키 없음 등
            errors[operation] = str(error)
            log(f"[{operation}] 수집 실패: {error}")
    return errors


def check_bronze(snapshot, root, collect_errors):
    """수집 결과 검증. {오퍼레이션: 문제 설명} 을 돌려준다 (비어 있으면 통과)."""
    problems = dict(collect_errors)
    for operation, service in ALL_OPERATIONS.items():
        if operation in problems:
            continue
        manifest_path = Path(root) / "bronze" / service / operation / f"snapshot={snapshot}" / "_manifest.json"
        if not manifest_path.exists():
            problems[operation] = "_manifest.json 없음"
            continue
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        issues = []
        if m["items_total"] != m["total_count"]:
            issues.append(f"건수 {m['items_total']:,}/{m['total_count']:,}")
        if m["missing_pages"]:
            issues.append(f"빠진 페이지 {m['missing_pages'][:10]}")
        if m["failed_pages"]:
            issues.append(f"실패한 페이지 {m['failed_pages'][:10]}")
        if issues:
            problems[operation] = ", ".join(issues)
        elif m["total_count_changes"]:
            # 수집 중에 원본 데이터가 갱신된 경우. 건수는 맞아서 통과시키되 기록은 남긴다
            log(f"[{operation}] 주의: 수집 중 전체 건수가 바뀜 {m['total_count_changes']}")
    return problems


def main():
    parser = argparse.ArgumentParser(description="수집 → bronze 검증 → silver 빌드")
    parser.add_argument("--snapshot", default=date.today().isoformat())
    parser.add_argument("--root", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    log(f"1/3 수집 시작 snapshot={args.snapshot} API {len(ALL_OPERATIONS)}개")
    collect_errors = collect_all(args.snapshot, args.root)

    log("2/3 bronze 검증")
    problems = check_bronze(args.snapshot, args.root, collect_errors)
    if problems:
        log(f"bronze 검증 실패 {len(problems)}개 — silver 를 만들지 않음. 같은 --snapshot 으로 다시 실행하면 이어받는다")
        for operation, problem in problems.items():
            log(f"  {operation}: {problem}")
        sys.exit(1)
    log(f"bronze 검증 통과 ({len(ALL_OPERATIONS)}개)")

    log("3/3 silver 빌드")
    build = subprocess.run([sys.executable, str(PIPELINE_DIR / "silver" / "build.py"), "--snapshot", args.snapshot,
                            "--root", args.root])
    if build.returncode != 0:
        log("silver 빌드 실패 — _latest.json 은 이전 버전 그대로")
        sys.exit(build.returncode)
    log("완료")


if __name__ == "__main__":
    main()

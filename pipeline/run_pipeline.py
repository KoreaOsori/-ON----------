"""수집 → bronze 검증 → silver 빌드 → gold 빌드 → RDS 적재 → 오래된 스냅샷 정리를 차례로 실행한다. 스케줄러는 이 스크립트만 부르면 된다.

S3 가 bronze·silver·gold 의 원본이다. 각 단계는 앞 단계의 결과를 S3 에서 읽고 S3 에 쓴다 (디스크는 빌드 중 임시 폴더로만 씀).

  API → S3 bronze → S3 silver → S3 gold → RDS

  python pipeline/run_pipeline.py                                   # 오늘 날짜 스냅샷 (EC2)
  python pipeline/run_pipeline.py --snapshot 2026-10-14             # 중간에 끊긴 수집 이어받기 (같은 날짜로 다시 실행)
  python pipeline/run_pipeline.py --snapshot 2026-10-13 --skip-collect   # S3 에 이미 있는 bronze 로 silver·gold·RDS 만
  python pipeline/run_pipeline.py --gold-host localhost             # 내 PC 에서 SSM 터널로 RDS 에 적재

1. 수집: 등록된 API 전부를 S3 bronze 에 (S3 에 이미 있는 페이지는 건너뜀). --skip-collect 면 생략
2. bronze 검증: API 마다 S3 _manifest.json 의 판정(count_match: 받은 건수 = 전체 건수, 식품안전나라는 수집 중 목록이 안 바뀜),
   빠진 페이지 0, 실패한 페이지 0
3. silver 빌드: S3 bronze → S3 silver (검증에 실패하면 S3 에 올리지 않고 silver/_latest.json 도 그대로)
4. gold 빌드: S3 silver → S3 gold (이미 만든 silver 면 건너뜀. 검사에 실패하면 올리지 않음)
5. RDS 적재: S3 gold → RDS (이미 적재한 gold 면 건너뜀. 실패하면 기존 gold 유지)
6. 오래된 스냅샷 정리: 1~5 가 모두 성공했을 때만. 완성된 스냅샷을 bronze 2·silver 4·gold 2 개만 남긴다 (retention.py)
앞 단계가 실패하면 뒤 단계는 실행하지 않고 종료 코드 1 (RDS 접속 실패는 2: S3 gold 는 완성됐으니 RDS 를 켜고 5단계만 다시)
"""

import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR / "collect"))

from collect import (  # noqa: E402
    ALL_OPERATIONS, DEFAULT_ROWS, FOOD_SAFETY_ROWS, bronze_prefix, collect_operation, get_service_key, is_food_safety,
)
from s3store import DEFAULT_BUCKET, Store  # noqa: E402


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def collect_all(snapshot, store):
    """API 마다 수집. 한 API 가 실패해도 나머지는 계속 받는다."""
    errors = {}
    for operation in ALL_OPERATIONS:
        rows = FOOD_SAFETY_ROWS if is_food_safety(operation) else DEFAULT_ROWS
        try:
            collect_operation(operation, snapshot, store, rows, get_service_key(operation))
        except (SystemExit, Exception) as error:  # 1쪽 실패, 키 없음 등
            errors[operation] = str(error)
            log(f"[{operation}] 수집 실패: {error}")
    return errors


def check_bronze(snapshot, store, collect_errors):
    """S3 수집 결과 검증. {오퍼레이션: 문제 설명} 을 돌려준다 (비어 있으면 통과)."""
    problems = dict(collect_errors)
    for operation in ALL_OPERATIONS:
        if operation in problems:
            continue
        m = store.get_json(bronze_prefix(operation, snapshot) + "_manifest.json")
        if m is None:
            problems[operation] = "_manifest.json 없음"
            continue
        if "count_match" not in m:
            problems[operation] = "수집이 끝나지 않음 (같은 --snapshot 으로 다시 실행하면 이어받는다)"
            continue
        issues = []
        if not m["count_match"]:  # 수집기가 내린 판정 (식품안전나라는 totalCount 대신 목록이 안 바뀌었는지로 판정)
            issues.append(f"건수 {m['items_total']:,} (API totalCount {m['total_count']:,})")
        if m["missing_pages"]:
            issues.append(f"빠진 페이지 {m['missing_pages'][:10]}")
        if m["failed_pages"]:
            issues.append(f"실패한 페이지 {m['failed_pages'][:10]}")
        issues += m.get("problems") or []
        if issues:
            problems[operation] = ", ".join(issues)
        elif m["total_count_changes"]:
            # 수집 중에 원본 데이터가 갱신된 경우. 건수는 맞아서 통과시키되 기록은 남긴다
            log(f"[{operation}] 주의: 수집 중 전체 건수가 바뀜 {m['total_count_changes']}")
    return problems


def run_step(script, *args):
    return subprocess.run([sys.executable, str(PIPELINE_DIR / script), *args]).returncode


def main():
    parser = argparse.ArgumentParser(description="수집 → bronze 검증 → silver → gold → RDS (S3 기준)")
    parser.add_argument("--snapshot", default=date.today().isoformat())
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--skip-collect", action="store_true", help="수집하지 않고 S3 에 이미 있는 bronze 스냅샷을 쓴다")
    parser.add_argument("--gold-host", help="RDS 호스트 덮어쓰기 (SSM 터널이면 localhost)")
    parser.add_argument("--gold-dsn", help="RDS 대신 이 DB 접속 문자열 (로컬 테스트용)")
    args = parser.parse_args()
    store = Store(args.bucket)
    log(f"버킷 {store.bucket}, snapshot={args.snapshot}")

    if args.skip_collect:
        log("1/6 수집 생략")
        collect_errors = {}
    else:
        log(f"1/6 수집 시작 API {len(ALL_OPERATIONS)}개 → s3://{store.bucket}/bronze/")
        collect_errors = collect_all(args.snapshot, store)

    log("2/6 bronze 검증")
    problems = check_bronze(args.snapshot, store, collect_errors)
    if problems:
        log(f"bronze 검증 실패 {len(problems)}개 — silver·gold 를 만들지 않음. 같은 --snapshot 으로 다시 실행하면 이어받는다")
        for operation, problem in problems.items():
            log(f"  {operation}: {problem}")
        sys.exit(1)
    log(f"bronze 검증 통과 ({len(ALL_OPERATIONS)}개)")

    log("3/6 silver 빌드 (S3 bronze → S3 silver)")
    code = run_step("silver/build.py", "--snapshot", args.snapshot, "--bucket", store.bucket)
    if code != 0:
        log("silver 빌드 실패 — S3 silver 는 이전 그대로, gold 는 만들지 않음")
        sys.exit(code)

    log("4/6 gold 빌드 (S3 silver → S3 gold)")
    code = run_step("gold/build.py", "--bucket", store.bucket)
    if code != 0:
        log("gold 빌드 실패 — S3 gold 는 이전 그대로, RDS 적재는 하지 않음")
        sys.exit(code)

    log("5/6 RDS 적재 (S3 gold → RDS)")
    target = ["--dsn", args.gold_dsn] if args.gold_dsn else ["--host", args.gold_host] if args.gold_host else []
    code = run_step("gold/load.py", "--bucket", store.bucket, *target)
    if code != 0:
        log("RDS 적재 실패 — S3 gold 는 완성, RDS 는 기존 gold 유지. 원인 해결 후 pipeline/gold/load.py 만 다시 실행하면 된다")
        sys.exit(code)

    log("6/6 오래된 스냅샷 정리 (모든 단계 성공)")
    code = run_step("retention.py", "--bucket", store.bucket, "--apply")
    if code != 0:
        log("스냅샷 정리 실패 — 데이터(S3 gold·RDS)는 완성. 다음 실행 때 다시 정리한다")
        sys.exit(code)
    log("완료")


if __name__ == "__main__":
    main()

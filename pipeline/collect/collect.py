"""식약처 공공 API(공공데이터포털, 식품안전나라)를 페이지 단위로 받아 S3 Bronze 에 원본 그대로 저장한다.

저장 경로: s3://{버킷}/bronze/{서비스}/{오퍼레이션}/snapshot={날짜}/page_00001.json, _manifest.json
- 받은 페이지는 바로 S3 에 쓴다 (디스크를 거치지 않음)
- S3 에 이미 있는 페이지는 건너뛴다 (이어받기). 진행 상황(페이지별 건수)은 50쪽마다 _manifest.json 에 남긴다
- 실패한 페이지는 3회 재시도 후 실패 목록에 남기고 다음 페이지로 넘어간다
- 끝나면 S3 목록 기준으로 누락 페이지와 건수 합계를 totalCount 와 대조한다. 끝난 _manifest.json 에만 count_match 가 있다
- 식품안전나라(C003)는 목록이 실시간으로 바뀌는데 total_count 는 늦게 갱신된다 (2026-10-19 확인: 전체 건수 45,940 인데
  실제 45,953행, 그날 신고된 제품이 목록 중간에 바로 들어옴). 그래서 total_count 대신
    · "데이터 없음"(INFO-200) 쪽이 나올 때까지 받고
    · 다 받은 뒤 1쪽과 마지막 쪽을 다시 받아 처음과 같은지(수집 중 목록이 안 바뀌었는지) 확인하고
    · 제품번호 중복이 없는지 확인한다. 셋 다 통과해야 count_match
  목록이 바뀌므로 이어받지 않고 매번 처음부터 받는다 (46쪽, 약 1분). 실패하면 바로 다시 받지 않고 다음 실행 때 처음부터 받는다:
  식품안전나라는 CHNG_DT 없이 1시간에 100번까지만 호출할 수 있어서 (INFO-320) 한 번 수집(46쪽 + 확인 3번 = 49번)을
  곧바로 반복하면 한도에 걸린다. 한도에 걸리면 남은 쪽을 받지 않고 바로 멈춘다
- 속도: EC2(미국 동부)에서 한국 API 를 받으면 쪽마다 왕복이 길어 느리다 (2026-10-19 전체 수집 5시간 35분).
  공공데이터포털 API 는 CONCURRENCY 쪽씩 동시에 받고, 접속은 재사용한다 (내 PC 측정: 쪽당 1.32초 → 0.31초).
  식품안전나라는 호출 한도와 "데이터 없음"으로 끝을 찾는 방식 때문에 한 쪽씩 받는다

  python pipeline/collect/collect.py getDrbEasyDrugList C003 --snapshot 2026-10-19
  python pipeline/collect/collect.py --all
"""

import argparse
import functools
import json
import math
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from operations import FOOD_SAFETY_OPERATIONS, OPERATIONS  # noqa: E402
from s3store import Store  # noqa: E402

BASE_URL = "https://apis.data.go.kr/1471000"
FOOD_SAFETY_URL = "https://openapi.foodsafetykorea.go.kr/api"
DEFAULT_ROWS = 500
FOOD_SAFETY_ROWS = 1000  # 식품안전나라는 한 번에 최대 1,000건
ALL_OPERATIONS = {**OPERATIONS, **FOOD_SAFETY_OPERATIONS}
MAX_RETRIES = 3
TIMEOUT_SECONDS = 120
CONCURRENCY = 4  # 공공데이터포털 API 를 동시에 받는 쪽 수
HTTP = urllib3.PoolManager(maxsize=CONCURRENCY, retries=False, timeout=TIMEOUT_SECONDS)  # 접속 재사용 (스레드 안전)
FOOD_SAFETY_KEYS = {"C003": "PRDLST_REPORT_NO"}  # 식품안전나라 목록의 제품 키 (중복 검사)
NO_DATA = "INFO-200"  # 식품안전나라: 해당하는 데이터가 없습니다 (마지막 쪽 다음)
RATE_LIMITED = "INFO-320"  # 식품안전나라: 1시간 호출 한도 초과
CHECKPOINT_PAGES = 50  # 이 쪽수마다 진행 상황을 S3 _manifest.json 에 남긴다 (끊겼을 때 받은 페이지의 건수를 다시 읽지 않도록)
APP_SECRET = "pill-check/dev/app"  # API 키는 Secrets Manager 에서 (로컬은 AWS 자격 증명, EC2 는 IAM 역할)
REGION = "us-east-1"


def is_food_safety(operation):
    return operation in FOOD_SAFETY_OPERATIONS


@functools.cache
def read_app_secret():
    import boto3

    return json.loads(boto3.client("secretsmanager", region_name=REGION)
                      .get_secret_value(SecretId=APP_SECRET)["SecretString"])


def get_service_key(operation):
    name = "FOOD_SAFETY_API" if is_food_safety(operation) else "E_Drug_API"
    key = read_app_secret().get(name)
    if not key:
        raise SystemExit(f"Secrets Manager {APP_SECRET} 에 {name} 값이 없습니다.")
    return key


class RateLimited(RuntimeError):
    """다시 시도해도 소용없는 오류 (호출 한도). 재시도하지 않는다."""


def get_json(url, key):
    """GET 해서 JSON 으로. 오류 메시지에 들어간 API 키는 가린다."""
    try:
        response = HTTP.request("GET", url)
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return json.loads(response.data.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(str(exc).replace(key, "***")) from None


def fetch_food_safety_page(operation, page_no, rows, key):
    start, end = (page_no - 1) * rows + 1, page_no * rows
    data = get_json(f"{FOOD_SAFETY_URL}/{key}/{operation}/json/{start}/{end}", key)
    result = (data.get(operation) or data).get("RESULT") or {}
    if result.get("CODE") == NO_DATA:  # 마지막 쪽 다음: 빈 응답으로 돌려준다
        return {operation: {"RESULT": result, "row": []}}
    if result.get("CODE") == RATE_LIMITED:
        raise RateLimited(f"API 호출 한도 초과: {result}")
    if result.get("CODE") != "INFO-000":
        raise RuntimeError(f"API 오류 응답: {result}")
    return data


def fetch_page(service, operation, page_no, rows, key):
    if is_food_safety(operation):
        return fetch_food_safety_page(operation, page_no, rows, key)
    query = urlencode({"serviceKey": key, "pageNo": page_no, "numOfRows": rows, "type": "json"})
    data = get_json(f"{BASE_URL}/{service}/{operation}?{query}", key)
    header = data.get("header") or {}
    if header.get("resultCode") != "00" or "body" not in data:
        raise RuntimeError(f"API 오류 응답: {header}")
    return data


def total_count_of(response, operation):
    if is_food_safety(operation):
        return int(response[operation]["total_count"])
    return int(response["body"]["totalCount"])


def count_items_of(response, operation):
    if is_food_safety(operation):
        return len(response[operation].get("row") or [])
    return count_items(response["body"])


def count_items(body):
    items = body.get("items")
    if not items:
        return 0
    if isinstance(items, dict):
        items = items.get("item", [])
        if isinstance(items, dict):
            return 1
    return len(items)


def fetch_with_retry(service, operation, page_no, rows, key):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_page(service, operation, page_no, rows, key), None
        except RateLimited as exc:
            return None, exc
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return None, last_error


def bronze_prefix(operation, snapshot):
    return f"bronze/{ALL_OPERATIONS[operation]}/{operation}/snapshot={snapshot}/"


def page_numbers(keys):
    return {int(m.group(1)) for key in keys if (m := re.search(r"/page_(\d+)\.json$", key))}


def food_safety_keys(response, operation):
    return [row.get(FOOD_SAFETY_KEYS[operation]) for row in response[operation].get("row") or []]


def check_food_safety(store, operation, page_key, present, rows, key):
    """식품안전나라: 수집 중 목록이 바뀌지 않았는지(1쪽·마지막 쪽 다시 받아 비교), 제품번호 중복이 없는지. 문제 목록을 돌려준다."""
    service = ALL_OPERATIONS[operation]
    problems = []
    keys = []
    for page_no in present:
        keys += food_safety_keys(store.get_json(page_key(page_no))["response"], operation)
    duplicates = len(keys) - len(set(keys))
    if duplicates:
        problems.append(f"제품번호 중복 {duplicates}개 (수집 중 목록이 밀림)")
    for page_no in (present[0], present[-1], present[-1] + 1):
        again, error = fetch_with_retry(service, operation, page_no, rows, key)
        if again is None:
            problems.append(f"{page_no}쪽 다시 받기 실패: {error}")
            continue
        saved = food_safety_keys(store.get_json(page_key(page_no))["response"], operation) if page_no in present else []
        if food_safety_keys(again, operation) != saved:
            problems.append(f"{page_no}쪽이 수집 후 바뀜 ({len(saved)}행 → {count_items_of(again, operation)}행): 수집 중 목록이 바뀜")
    return problems


def collect_operation(operation, snapshot, store, rows, key):
    service = ALL_OPERATIONS[operation]
    food_safety = is_food_safety(operation)
    prefix = bronze_prefix(operation, snapshot)
    manifest_key = prefix + "_manifest.json"
    previous = store.get_json(manifest_key) or {}
    started_at = previous.get("started_at") or datetime.now().isoformat(timespec="seconds")
    # 식품안전나라는 목록이 바뀌므로 이어받지 않고 처음부터 받아 덮어쓴다
    page_items = {} if food_safety else {int(n): c for n, c in (previous.get("page_items") or {}).items()}  # 쪽 → 항목 수
    existing = set() if food_safety else page_numbers(store.list(prefix))

    def page_key(page_no):
        return prefix + f"page_{page_no:05d}.json"

    def save_page(page_no, response):
        meta = {
            "service": service,
            "operation": operation,
            "page_no": page_no,
            "num_of_rows": rows,
            "snapshot": snapshot,
            "collected_at": datetime.now().isoformat(timespec="seconds"),
        }
        store.put_json(page_key(page_no), {"meta": meta, "response": response})
        with lock:  # 여러 스레드가 동시에 쓴다
            page_items[page_no] = count_items_of(response, operation)

    def save_progress():
        with lock:
            snapshot_items = dict(page_items)
        store.put_json(manifest_key, {
            "service": service, "operation": operation, "snapshot": snapshot, "rows": rows,
            "status": "수집 중", "started_at": started_at, "page_items": snapshot_items,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })

    def fetch_and_save(page_no):
        """한 쪽을 받아 S3 에 저장 (스레드에서 실행). (쪽, 그 쪽의 totalCount 또는 None, 오류)."""
        response, error = fetch_with_retry(service, operation, page_no, rows, key)
        if response is None:
            return page_no, None, error
        save_page(page_no, response)
        return page_no, total_count_of(response, operation), None

    lock = threading.Lock()

    # 1쪽으로 totalCount 확인
    if 1 in existing:
        saved = store.get_json(page_key(1))
        if saved["meta"]["num_of_rows"] != rows:  # 쪽 크기가 다르면 이미 받은 쪽과 겹치거나 빠진다
            raise SystemExit(f"[{operation}] 이미 받은 쪽은 {saved['meta']['num_of_rows']}건씩인데 지금 {rows}건씩 — "
                             f"같은 --rows 로 이어받을 것")
        first = saved["response"]
        page_items[1] = count_items_of(first, operation)
    else:
        first, error = fetch_with_retry(service, operation, 1, rows, key)
        if first is None:
            raise SystemExit(f"[{operation}] 1쪽 수집 실패: {error}")
        save_page(1, first)
    total_count = total_count_of(first, operation) if page_items[1] else 0
    pages = math.ceil(total_count / rows)
    print(f"[{operation}] totalCount={total_count} pages={pages} (S3 에 이미 있는 쪽 {len(existing)})", flush=True)

    failed_pages = []
    total_count_changes = []

    def record(page_no, current_total, error):
        if current_total is None:
            failed_pages.append(page_no)
            print(f"[{operation}] {page_no}쪽 실패: {error}", flush=True)
        elif current_total != total_count:
            total_count_changes.append({"page": page_no, "total_count": current_total})
            print(f"[{operation}] 경고: {page_no}쪽에서 totalCount가 {total_count} → {current_total}로 바뀜", flush=True)

    if food_safety:
        # 한 쪽씩, "데이터 없음" 쪽이 나올 때까지 (totalCount 가 늦게 갱신되고, 호출 한도가 있다)
        page_no = 1
        while True:
            page_no += 1
            response, error = fetch_with_retry(service, operation, page_no, rows, key)
            if response is None:
                record(page_no, None, error)
                if isinstance(error, RateLimited):
                    break  # 호출 한도: 남은 쪽도 모두 실패하므로 바로 멈춘다 (검증에서 실패 처리)
                if failed_pages[-MAX_RETRIES:] == list(range(page_no - MAX_RETRIES + 1, page_no + 1)):
                    break  # 연속으로 실패하면 끝을 알 수 없으므로 멈춘다 (검증에서 실패 처리)
                continue
            if not count_items_of(response, operation):
                break  # 마지막 쪽 다음
            save_page(page_no, response)
            record(page_no, total_count_of(response, operation), None)
    else:
        # totalCount 로 정한 쪽까지, S3 에 없는 쪽만 CONCURRENCY 개씩 동시에
        todo = [n for n in range(2, pages + 1) if n not in existing]
        with ThreadPoolExecutor(CONCURRENCY) as pool:
            for done, (page_no, current_total, error) in enumerate(pool.map(fetch_and_save, todo), start=1):
                record(page_no, current_total, error)
                if done % CHECKPOINT_PAGES == 0:
                    save_progress()
                    print(f"[{operation}] {done}/{len(todo)}", flush=True)
        failed_pages.sort()

    if food_safety:  # 이전 시도에서 받았지만 이번 목록에는 없는 뒤쪽 페이지는 지운다
        for n in sorted(page_numbers(store.list(prefix))):
            if n > max(page_items):
                store.s3.delete_object(Bucket=store.bucket, Key=page_key(n))
                print(f"[{operation}] 이번 목록보다 뒤의 {n}쪽 삭제 (이전 수집에서 남은 것)", flush=True)

    # S3 목록 기준 검증 (실제로 올라간 페이지로 누락과 건수를 확인)
    present = sorted(page_numbers(store.list(prefix)))
    last_page = (present[-1] if present else 0) if food_safety else pages  # 식품안전나라: 실제로 받은 마지막 쪽
    missing_pages = sorted(set(range(1, last_page + 1)) - set(present))
    unknown = [n for n in present if n not in page_items]  # 진행 기록 전에 끊긴 이전 실행이 올린 페이지
    if unknown:
        print(f"[{operation}] 건수 확인을 위해 S3 에서 {len(unknown)}쪽을 다시 읽음", flush=True)
    for n in unknown:
        page_items[n] = count_items_of(store.get_json(page_key(n))["response"], operation)
    items_total = sum(page_items[n] for n in present)
    short_pages = [n for n in present if n < last_page and page_items[n] != rows]

    if food_safety:
        if not present:
            problems = ["1쪽 없음"]
        elif failed_pages:
            problems = []  # 이미 실패. 확인 호출로 호출 한도를 더 쓰지 않는다
        else:
            problems = check_food_safety(store, operation, page_key, present, rows, key)
        count_match = not problems and not missing_pages and not failed_pages and not short_pages
        if total_count != items_total:
            print(f"[{operation}] 참고: API totalCount {total_count} != 실제 받은 행 {items_total} (totalCount 가 늦게 갱신됨)", flush=True)
    else:
        problems = []
        count_match = items_total == total_count and not missing_pages

    manifest = {
        "service": service,
        "operation": operation,
        "snapshot": snapshot,
        "rows": rows,
        "total_count": total_count,  # API 가 알려 준 값 (식품안전나라는 실제와 다를 수 있음)
        "pages": last_page,
        "started_at": started_at,
        "failed_pages": failed_pages,
        "short_pages": short_pages,
        "total_count_changes": total_count_changes,
        "missing_pages": missing_pages,
        "items_total": items_total,
        "problems": problems,
        "count_match": count_match,
        "status": "완료",
        "page_items": {n: page_items[n] for n in present},
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    store.put_json(manifest_key, manifest)
    status = "OK" if manifest["count_match"] else "불일치"
    print(f"[{operation}] {status}: items={items_total}/{total_count} pages={last_page} missing={len(missing_pages)} "
          f"failed={len(failed_pages)} short={len(short_pages)} {problems or ''}", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description="식약처 API Bronze 수집")
    parser.add_argument("operations", nargs="*", help="오퍼레이션 이름 (여러 개 가능)")
    parser.add_argument("--all", action="store_true", help="등록된 오퍼레이션 전부")
    parser.add_argument("--rows", type=int,
                        help=f"한 번에 받는 건수 (기본: 공공데이터포털 {DEFAULT_ROWS}, 식품안전나라 {FOOD_SAFETY_ROWS})")
    parser.add_argument("--snapshot", default=date.today().isoformat())
    parser.add_argument("--bucket")
    args = parser.parse_args()

    targets = list(ALL_OPERATIONS) if args.all else args.operations
    unknown = [name for name in targets if name not in ALL_OPERATIONS]
    if not targets or unknown:
        raise SystemExit(f"오퍼레이션을 지정하세요. 알 수 없는 이름: {unknown}\n사용 가능: {list(ALL_OPERATIONS)}")

    store = Store(args.bucket)
    mismatched = []
    for operation in targets:
        rows = args.rows or (FOOD_SAFETY_ROWS if is_food_safety(operation) else DEFAULT_ROWS)
        if not collect_operation(operation, args.snapshot, store, rows, get_service_key(operation))["count_match"]:
            mismatched.append(operation)
    if mismatched:  # 종료 코드 1 (운영은 run_pipeline.py 가 매니페스트로 따로 검증한다)
        raise SystemExit(f"수집 불일치: {mismatched}")


if __name__ == "__main__":
    main()

"""식약처 공공 API(공공데이터포털, 식품안전나라)를 페이지 단위로 받아 Bronze에 원본 그대로 저장한다.

저장 경로: {out}/bronze/{서비스}/{오퍼레이션}/snapshot={날짜}/page_00001.json
- 이미 받은 페이지는 건너뛴다 (이어받기)
- 실패한 페이지는 3회 재시도 후 실패 목록에 남기고 다음 페이지로 넘어간다
- 끝나면 파일 기준으로 누락 페이지와 건수 합계를 totalCount와 대조한다
"""

import argparse
import json
import math
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv

from operations import FOOD_SAFETY_OPERATIONS, OPERATIONS

BASE_URL = "https://apis.data.go.kr/1471000"
FOOD_SAFETY_URL = "https://openapi.foodsafetykorea.go.kr/api"
DEFAULT_ROWS = 500
FOOD_SAFETY_ROWS = 1000  # 식품안전나라는 한 번에 최대 1,000건
ALL_OPERATIONS = {**OPERATIONS, **FOOD_SAFETY_OPERATIONS}
MAX_RETRIES = 3
TIMEOUT_SECONDS = 120
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "s3"


def is_food_safety(operation):
    return operation in FOOD_SAFETY_OPERATIONS


def get_service_key(operation):
    load_dotenv()
    name = "FOOD_SAFETY_API" if is_food_safety(operation) else "E_Drug_API"
    key = os.environ.get(name)
    if not key:
        raise SystemExit(f"{name} 환경변수가 비어 있습니다. .env를 확인하세요.")
    return key


def fetch_food_safety_page(operation, page_no, rows, key):
    start, end = (page_no - 1) * rows + 1, page_no * rows
    url = f"{FOOD_SAFETY_URL}/{key}/{operation}/json/{start}/{end}"
    try:
        with urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(str(exc).replace(key, "***")) from None
    result = (data.get(operation) or {}).get("RESULT") or {}
    if result.get("CODE") != "INFO-000":
        raise RuntimeError(f"API 오류 응답: {result}")
    return data


def fetch_page(service, operation, page_no, rows, key):
    if is_food_safety(operation):
        return fetch_food_safety_page(operation, page_no, rows, key)
    query = urlencode({"serviceKey": key, "pageNo": page_no, "numOfRows": rows, "type": "json"})
    url = f"{BASE_URL}/{service}/{operation}?{query}"
    try:
        with urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            text = resp.read().decode("utf-8")
        data = json.loads(text)
    except Exception as exc:
        raise RuntimeError(str(exc).replace(key, "***")) from None
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


def write_json(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def fetch_with_retry(service, operation, page_no, rows, key):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_page(service, operation, page_no, rows, key), None
        except Exception as exc:
            last_error = exc
            time.sleep(2 * attempt)
    return None, last_error


def collect_operation(operation, snapshot, out_root, rows, key):
    service = ALL_OPERATIONS[operation]
    out_dir = Path(out_root) / "bronze" / service / operation / f"snapshot={snapshot}"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "_manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    started_at = previous.get("started_at") or datetime.now().isoformat(timespec="seconds")

    def page_path(page_no):
        return out_dir / f"page_{page_no:05d}.json"

    def save_page(page_no, response):
        meta = {
            "service": service,
            "operation": operation,
            "page_no": page_no,
            "num_of_rows": rows,
            "snapshot": snapshot,
            "collected_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_json(page_path(page_no), {"meta": meta, "response": response})

    # 1쪽으로 totalCount 확인
    if page_path(1).exists():
        first = json.loads(page_path(1).read_text(encoding="utf-8"))["response"]
    else:
        first, error = fetch_with_retry(service, operation, 1, rows, key)
        if first is None:
            raise SystemExit(f"[{operation}] 1쪽 수집 실패: {error}")
        save_page(1, first)
    total_count = total_count_of(first, operation)
    pages = math.ceil(total_count / rows)
    print(f"[{operation}] totalCount={total_count} pages={pages}")

    failed_pages = []
    total_count_changes = []
    for page_no in range(2, pages + 1):
        if page_path(page_no).exists():
            continue
        response, error = fetch_with_retry(service, operation, page_no, rows, key)
        if response is None:
            failed_pages.append(page_no)
            print(f"[{operation}] {page_no}쪽 실패: {error}")
            continue
        save_page(page_no, response)
        current_total = total_count_of(response, operation)
        if current_total != total_count:
            total_count_changes.append({"page": page_no, "total_count": current_total})
            print(f"[{operation}] 경고: {page_no}쪽에서 totalCount가 {total_count} → {current_total}로 바뀜")
        if page_no % 50 == 0:
            print(f"[{operation}] {page_no}/{pages}")

    # 파일 기준 검증 (매니페스트가 아니라 실제 파일로 누락과 건수를 확인)
    present = sorted(int(m.group(1)) for p in out_dir.glob("page_*.json") if (m := re.match(r"page_(\d+)\.json$", p.name)))
    missing_pages = sorted(set(range(1, pages + 1)) - set(present))
    items_total = 0
    short_pages = []
    for page_no in present:
        response = json.loads(page_path(page_no).read_text(encoding="utf-8"))["response"]
        n = count_items_of(response, operation)
        items_total += n
        if page_no < pages and n != rows:
            short_pages.append(page_no)

    manifest = {
        "service": service,
        "operation": operation,
        "snapshot": snapshot,
        "rows": rows,
        "total_count": total_count,
        "pages": pages,
        "started_at": started_at,
        "failed_pages": failed_pages,
        "short_pages": short_pages,
        "total_count_changes": total_count_changes,
        "missing_pages": missing_pages,
        "items_total": items_total,
        "count_match": items_total == total_count and not missing_pages,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(manifest_path, manifest)
    status = "OK" if manifest["count_match"] else "불일치"
    print(f"[{operation}] {status}: items={items_total}/{total_count} missing={len(missing_pages)} failed={len(failed_pages)} short={len(short_pages)}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="식약처 API Bronze 수집")
    parser.add_argument("operations", nargs="*", help="오퍼레이션 이름 (여러 개 가능)")
    parser.add_argument("--all", action="store_true", help="등록된 오퍼레이션 전부")
    parser.add_argument("--rows", type=int,
                        help=f"한 번에 받는 건수 (기본: 공공데이터포털 {DEFAULT_ROWS}, 식품안전나라 {FOOD_SAFETY_ROWS})")
    parser.add_argument("--snapshot", default=date.today().isoformat())
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    targets = list(ALL_OPERATIONS) if args.all else args.operations
    unknown = [name for name in targets if name not in ALL_OPERATIONS]
    if not targets or unknown:
        raise SystemExit(f"오퍼레이션을 지정하세요. 알 수 없는 이름: {unknown}\n사용 가능: {list(ALL_OPERATIONS)}")

    for operation in targets:
        rows = args.rows or (FOOD_SAFETY_ROWS if is_food_safety(operation) else DEFAULT_ROWS)
        collect_operation(operation, args.snapshot, args.out, rows, get_service_key(operation))


if __name__ == "__main__":
    main()

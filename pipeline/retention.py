"""S3 의 오래된 스냅샷 정리: 층마다 완성된 스냅샷을 최근 KEEP 개만 남긴다 (bronze 2, silver 4, gold 2).

  python pipeline/retention.py            # 지울 목록만 보여 줌 (기본, 아무것도 안 지움)
  python pipeline/retention.py --apply    # 실제로 지움 (run_pipeline.py 는 모든 단계가 성공했을 때만 이걸 부른다)

silver 를 4개 두는 이유: gold 의 "이전 수집 유지"가 이전 silver 병용금기 스냅샷을 최대 3개 본다 (현재 + 3).

최신본 생성이 잘못돼도 정상 데이터를 밀어내지 않도록:
1. run_pipeline.py 는 수집·silver·gold·RDS 가 모두 성공했을 때만 정리한다 (실패하면 아무것도 지우지 않음)
2. 개수는 완성된 스냅샷만 센다. bronze = 22개 API 매니페스트가 모두 count_match, silver·gold = 모든 테이블 파일이 있고
   _latest.json 이 가리키는 날짜 이하. 덜 만든 스냅샷은 세지 않고, 남길 가장 오래된 스냅샷보다 최신이면 지우지 않는다
3. _latest.json 이 가리키는 스냅샷(과 그 gold 를 만든 silver, 그 silver 를 만든 bronze)은 개수와 상관없이 지우지 않는다.
   지운 파일도 버킷 버전 관리로 30일 동안 복구할 수 있다
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR / "collect"))

from collect import ALL_OPERATIONS  # noqa: E402
from s3store import DEFAULT_BUCKET, Store  # noqa: E402

KEEP = {"bronze": 2, "silver": 4, "gold": 2}


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def snapshot_dates(store, prefix):
    return {name.removeprefix("snapshot=") for name in store.folders(prefix) if name.startswith("snapshot=")}


def bronze_snapshots(store):
    """{날짜: 완성 여부, 그 날짜의 폴더 목록}. 완성 = 모든 API 에 매니페스트가 있고 count_match."""
    folders = {op: f"bronze/{svc}/{op}/" for op, svc in ALL_OPERATIONS.items()}
    dates = {op: snapshot_dates(store, prefix) for op, prefix in folders.items()}
    result = {}
    for date in set().union(*dates.values()):
        complete = all(date in dates[op] for op in folders)
        if complete:
            for prefix in folders.values():
                manifest = store.get_json(f"{prefix}snapshot={date}/_manifest.json")
                if not (manifest and manifest.get("count_match")):
                    complete = False
                    break
        result[date] = (complete, [f"{p}snapshot={date}/" for op, p in folders.items() if date in dates[op]])
    return result


def table_snapshots(store, layer, tables, latest_date):
    """silver·gold: 완성 = 모든 테이블에 data.parquet 이 있고 _latest.json 이 가리키는 날짜 이하."""
    dates = {t: snapshot_dates(store, f"{layer}/{t}/") for t in tables}
    result = {}
    for date in set().union(*dates.values()):
        complete = latest_date is not None and date <= latest_date and all(
            date in dates[t] and store.list(f"{layer}/{t}/snapshot={date}/data.parquet") for t in tables)
        result[date] = (complete, [f"{layer}/{t}/snapshot={date}/" for t in tables if date in dates[t]])
    return result


def plan(store):
    """층마다 (남길 날짜, 지울 날짜와 폴더). 지울 것이 없으면 빈 목록."""
    silver_latest = store.get_json("silver/_latest.json")
    gold_latest = store.get_json("gold/_latest.json")
    if not silver_latest or not gold_latest:
        log("silver 또는 gold 의 _latest.json 이 없어 정리하지 않음")
        return {}
    pinned = {  # 3) _latest 가 가리키는 스냅샷과 그것을 만든 이전 층
        "gold": {gold_latest["snapshot"]},
        "silver": {silver_latest["snapshot"], *gold_latest["silver_tables"].values()},
        "bronze": {silver_latest["snapshot"]},
    }
    layers = {
        "bronze": bronze_snapshots(store),
        "silver": table_snapshots(store, "silver", list(silver_latest["tables"]), silver_latest["snapshot"]),
        "gold": table_snapshots(store, "gold", list(gold_latest["row_counts"]), gold_latest["snapshot"]),
    }
    result = {}
    for layer, snaps in layers.items():
        complete = sorted((d for d, (ok, _) in snaps.items() if ok), reverse=True)
        keep = set(complete[:KEEP[layer]]) | pinned[layer]
        oldest_kept = min(keep)
        delete = [d for d in sorted(snaps) if d not in keep and d < oldest_kept]  # 2) 남길 것보다 최신인 덜 만든 것은 안 지움
        result[layer] = (sorted(d for d in snaps if d not in delete), [(d, snaps[d][0], snaps[d][1]) for d in delete])
    return result


def delete_prefix(store, prefix):
    keys = list(store.list(prefix))
    for i in range(0, len(keys), 1000):
        response = store.s3.delete_objects(Bucket=store.bucket,
                                           Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})
        if response.get("Errors"):
            raise RuntimeError(f"s3://{store.bucket}/{prefix} 삭제 실패: {response['Errors'][:3]}")
    return len(keys)


def main():
    parser = argparse.ArgumentParser(description="S3 오래된 스냅샷 정리 (기본은 목록만)")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--apply", action="store_true", help="실제로 지운다")
    args = parser.parse_args()
    store = Store(args.bucket)
    for layer, (keep, delete) in plan(store).items():
        log(f"{layer}: 남김 {keep} (최근 완성 {KEEP[layer]}개, _latest 관련, 그보다 최신인 것), 지울 스냅샷 {len(delete)}개")
        for date, complete, prefixes in delete:
            state = "완성" if complete else "덜 만든 것"
            if args.apply:
                count = sum(delete_prefix(store, p) for p in prefixes)
                log(f"  {date} ({state}) 삭제: 파일 {count:,}개")
            else:
                log(f"  {date} ({state}) 지울 예정: 폴더 {len(prefixes)}개 (--apply 로 실행)")


if __name__ == "__main__":
    main()

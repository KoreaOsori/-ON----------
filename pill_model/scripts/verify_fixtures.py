"""
서버(컨테이너) 결과 = Colab 결과인지 fixtures 로 대조한다 (plan.md 3-5). LLM 은 호출하지 않는다.

실행 (컨테이너 안, /app 에서):
    python -m scripts.verify_fixtures --fixtures /app/tests/fixtures

판정은 단계적으로 (지문이 달라도 바로 실패로 끝내지 않음):
  ① 글자 목록 동일(필수)  ② 확신도 차이  ③ 최종 결과 동일
처방전은 OCR 원문을 출력하지 않는다 (개인정보) — 줄 수·지문·판정 비교 결과만 출력.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from app.ocr_engine import load_models


def pill_fp(reads):
    """알약 지문 (P-E1): 회전:글자|확신도 4자리"""
    s = "\n".join(f"{r['rot']}:{t}|{sc:.4f}" for r in reads for t, sc in zip(r["texts"], r["scores"]))
    return hashlib.sha256(s.encode()).hexdigest()


def rx_fp(lines):
    """처방전 지문 (R-E3b): 글자|확신도 4자리 (좌표 제외)"""
    s = "\n".join(f"{l['text']}|{l['score']:.4f}" for l in lines)
    return hashlib.sha256(s.encode()).hexdigest()


def same_json(a, b):
    # 튜플/리스트·float 표현 차이를 없애고 비교
    return json.loads(json.dumps(a, ensure_ascii=False)) == json.loads(json.dumps(b, ensure_ascii=False))


def check_pill(pill, fx_dir):
    results = []
    for jf in sorted((fx_dir / "pill").glob("*.expected.json")):
        fx = json.loads(jf.read_text(encoding="utf-8"))
        code = fx["code"]
        prepared, photo_rows = [], []
        for ph in fx["photos"]:                       # fixture photos 순서 그대로 (plan.md 3-5)
            path = fx_dir / "pill" / code / ph["file"]
            t = time.time()
            p = pill.prepare(str(path))
            sec = round(time.time() - t, 2)
            prepared.append(p)
            photo_rows.append(dict(
                file=ph["file"], sec=sec,
                fingerprint_same=pill_fp(p["reads"]) == ph["ocr_fingerprint"],
                texts_same=list(p["texts"]) == list(ph["texts"]),   # ① 필수
                texts=list(p["texts"]), texts_expected=list(ph["texts"]),
                quality_same=same_json(p["quality"], ph["quality"]),
            ))
        # ③ 최종 결과: 같은 사진 처리 결과를 그대로 넣어 analyze (OCR·CNN 재계산 없음)
        res = pill.analyze(None, None, shape=fx.get("shape"), _prepared=tuple(prepared))
        step = pill.next_step(res)["step"]
        exp = fx["expected"]
        top3 = [c["item_seq"] for c in res["candidates"][:3]]
        scores = [c["score"] for c in res["candidates"][:3]]
        final = dict(band=res["band"], imprint_match=res["imprint_match"], top3=top3, next_step=step)
        final_exp = dict(band=exp["band"], imprint_match=exp["imprint_match"], top3=exp["top3"], next_step=exp["next_step"])
        results.append(dict(
            kind="pill", code=code, photos=photo_rows,
            final_same=same_json(final, final_exp), final=final, final_expected=final_exp,
            score_max_diff=max(abs(a - b) for a, b in zip(scores, exp["scores"])) if len(scores) == len(exp["scores"]) else None,
        ))
    return results


def check_rx(rx, fx_dir):
    results = []
    for jf in sorted((fx_dir / "rx").glob("*.expected.json")):
        fx = json.loads(jf.read_text(encoding="utf-8"))
        path = fx_dir / "rx" / fx["image"]
        lines, meta = rx.read_lines(str(path))     # config per_call_limit=true → 공유 엔진에서 1280
        # ③ fixture 의 llm_result 를 넣어 decide() — LLM 재호출 결과로는 비교하지 않음
        drugs = rx.decide(lines, fx["llm_result"])
        n_diff = sum(1 for a, b in zip(drugs, fx["drugs"]) if not same_json(a, b)) + abs(len(drugs) - len(fx["drugs"]))
        results.append(dict(
            kind="rx", image=fx["image"], ocr_sec=meta["ocr_sec"],
            fingerprint_same=rx_fp(lines) == fx["ocr_fingerprint"],
            n_lines=len(lines), n_lines_expected=fx["n_lines"], n_lines_same=len(lines) == fx["n_lines"],   # ①
            decide_same=n_diff == 0, decide_diff_drugs=n_diff,
        ))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="tests/fixtures")
    ap.add_argument("--deploy", default="deploy")
    a = ap.parse_args()
    fx_dir = Path(a.fixtures)

    import cv2
    pill, rx, load_sec = load_models(a.deploy, load_llm=False)
    print(json.dumps(dict(load_sec=load_sec, cv2=cv2.__version__, shared_engine=pill.ocr is rx.ocr), ensure_ascii=False))

    rows = check_pill(pill, fx_dir) + check_rx(rx, fx_dir)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))

    ok_pill = all(r["final_same"] and all(p["texts_same"] for p in r["photos"]) for r in rows if r["kind"] == "pill")
    ok_rx = all(r["n_lines_same"] and r["decide_same"] for r in rows if r["kind"] == "rx")
    fp_all = all((all(p["fingerprint_same"] for p in r["photos"]) if r["kind"] == "pill" else r["fingerprint_same"]) for r in rows)
    print(json.dumps(dict(pill_pass=ok_pill, rx_pass=ok_rx, fingerprints_all_same=fp_all), ensure_ascii=False))
    sys.exit(0 if (ok_pill and ok_rx) else 1)


if __name__ == "__main__":
    main()

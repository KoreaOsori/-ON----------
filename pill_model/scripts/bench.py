"""
속도 측정 + 배경 제거 모델 비교 (plan.md 3-4, 6). 컨테이너 안 /app 에서 실행.

  python -m scripts.bench pill --runs 5              # 알약 fixture 3쌍 × 5회 (첫 요청 제외 평균)
  python -m scripts.bench rx --runs 5                # 처방전 OCR 만 3장 × 5회 (LLM 호출 없음)
  python -m scripts.bench llm-once                   # 처방전 1장 실제 Bedrock 1회 → AccessDenied 여부 (출력: 성공 여부·약 개수·시간만)
  python -m scripts.bench bg --models u2netp isnet-general-use silueta
        # fixture 알약(배경 제거됨)을 단색·무늬 배경에 합성 → rembg 로 다시 지움 → 시간·quality 통과율·Colab top3 일치율
        # ⚠ 합성 배경이라 실제 촬영 사진과 다를 수 있음 (실사진 실험은 --photos 폴더로 따로)

처방전 글자·LLM 입출력은 출력하지 않는다 (claude.md 1-7).
"""
import argparse
import io
import json
import statistics as st
import time
from pathlib import Path

FX = Path("tests/fixtures")


def _load(load_llm=False):
    from app.ocr_engine import load_models
    return load_models("deploy", load_llm=load_llm)


def _pairs():
    for jf in sorted((FX / "pill").glob("*.expected.json")):
        fx = json.loads(jf.read_text(encoding="utf-8"))
        yield fx, [FX / "pill" / fx["code"] / p["file"] for p in fx["photos"]]


def _summary(xs):
    rest = xs[1:] if len(xs) > 1 else xs        # 첫 요청(모델 준비) 제외
    return dict(n=len(rest), mean=round(st.mean(rest), 2), max=round(max(rest), 2), first=round(xs[0], 2))


def bench_pill(runs):
    from PIL import Image
    pill, _, load_sec = _load()
    out = dict(load_sec=load_sec)
    for fx, photos in _pairs():
        times = []
        for _ in range(runs + 1):
            t = time.time()
            ims = [Image.open(p) for p in photos]
            prep = tuple(pill.prepare(im) for im in ims)
            res = pill.analyze(None, None, shape=fx.get("shape"), _prepared=prep)
            pill.next_step(res)
            times.append(time.time() - t)
        out[fx["code"]] = dict(_summary(times), top3_same=[c["item_seq"] for c in res["candidates"][:3]] == fx["expected"]["top3"])
    print(json.dumps(out, ensure_ascii=False))


def bench_rx(runs):
    _, rx, load_sec = _load()
    out = dict(load_sec=load_sec)
    for i, jf in enumerate(sorted((FX / "rx").glob("*.expected.json"))):
        fx = json.loads(jf.read_text(encoding="utf-8"))
        data = (FX / "rx" / fx["image"]).read_bytes()
        times, n = [], None
        for _ in range(runs + 1):
            lines, meta = rx.read_lines(data)
            times.append(meta["ocr_sec"])
            n = len(lines)
        out[f"rx{i}"] = dict(_summary(times), n_lines_same=n == fx["n_lines"])
    print(json.dumps(out, ensure_ascii=False))


def llm_once():
    _, rx, _ = _load(load_llm=True)
    jf = sorted((FX / "rx").glob("*.expected.json"))[0]
    fx = json.loads(jf.read_text(encoding="utf-8"))
    try:
        res = rx.analyze((FX / "rx" / fx["image"]).read_bytes())
        print(json.dumps(dict(ok=True, json_ok=res["json_ok"], drugs=len(res["drugs"]), drugs_expected=len(fx["drugs"]),
                              timing_sec=res["timing_sec"], model=rx.cfg["llm"]["model_id"]), ensure_ascii=False))
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
        print(json.dumps(dict(ok=False, error=type(e).__name__, code=code), ensure_ascii=False))


def _composite(rgba, bg_kind, seed):
    """배경 제거된 알약을 배경 위에 올림 → 알파 없는 RGB (실제 촬영 사진 흉내)"""
    import numpy as np
    from PIL import Image
    w, h = rgba.size
    W, H = int(w * 2.2), int(h * 2.2)
    rng = np.random.default_rng(seed)
    if bg_kind == "plain":
        base = Image.new("RGB", (W, H), tuple(int(x) for x in rng.integers(150, 235, 3)))
    else:  # 무늬(체크) 배경 — quality 경고가 나야 정상
        yy, xx = np.mgrid[0:H, 0:W]
        chk = (((xx // 24) + (yy // 24)) % 2).astype(np.uint8)
        arr = np.stack([chk * 90 + 120, chk * 60 + 140, chk * 40 + 150], -1).astype(np.uint8)
        base = Image.fromarray(arr)
    base.paste(rgba, ((W - w) // 2, (H - h) // 2), rgba)
    buf = io.BytesIO()
    base.save(buf, format="JPEG", quality=92)   # 휴대폰 사진처럼 JPEG
    return buf.getvalue()


def bench_bg(models, per_code):
    from PIL import Image
    from app.bg import BgRemover, open_pill
    pill, _, _ = _load()
    rows = []
    for m in models:
        rem = BgRemover(m)
        open_pill(_composite(Image.open(next(_pairs())[1][0]).convert("RGBA"), "plain", 0), rem)   # 세션 준비 제외
        for kind in ("plain", "pattern"):
            times, q_ok, top1, top3 = [], 0, 0, 0
            n = 0
            for fx, photos in _pairs():
                for k in range(per_code):
                    srcs = [Image.open(p).convert("RGBA") for p in photos]
                    ims = []
                    for j, s in enumerate(srcs):
                        im, _, sec = open_pill(_composite(s, kind, k * 2 + j), rem)
                        ims.append(im)
                        times.append(sec)
                    prep = tuple(pill.prepare(im) for im in ims)
                    res = pill.analyze(None, None, shape=fx.get("shape"), _prepared=prep)
                    q_ok += res["quality"]["ok"]
                    got = [c["item_seq"] for c in res["candidates"][:3]]
                    top1 += got[:1] == fx["expected"]["top3"][:1]
                    top3 += fx["item_seq_true"] in got
                    n += 1
            rows.append(dict(model=m, background=kind, pairs=n, bg_sec_mean=round(st.mean(times), 2),
                             bg_sec_max=round(max(times), 2), quality_ok=f"{q_ok}/{n}", colab_top1_same=f"{top1}/{n}",
                             true_in_top3=f"{top3}/{n}"))
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["pill", "rx", "llm-once", "bg"])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--models", nargs="+", default=["u2netp", "isnet-general-use", "silueta"])
    ap.add_argument("--per-code", type=int, default=2)
    a = ap.parse_args()
    if a.mode == "pill":
        bench_pill(a.runs)
    elif a.mode == "rx":
        bench_rx(a.runs)
    elif a.mode == "llm-once":
        llm_once()
    else:
        bench_bg(a.models, a.per_code)


if __name__ == "__main__":
    main()

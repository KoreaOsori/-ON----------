"""
yakon_pill.py — 약ON 낱알 식별 모듈 (각인 OCR 규칙 + CNN 외형 + RRF 결합)

사용 예:
    from yakon_pill import PillIdentifier
    pid = PillIdentifier("/content/drive/MyDrive/pill_project/cnn/deploy")
    result = pid.analyze("front.png", "back.png", shape="타원형", top_k=5)

입력 사진: 배경이 제거된 RGBA 권장(알파 채널로 알약 영역을 찾음).
          배경이 있는 사진은 use_rembg=True면 rembg로 배경 제거(설치 필요), 아니면 사진 전체를 사용.
출력: dict(JSON 직렬화 가능) — 후보 Top-k, 근거(OCR 글자·일치 각인·각 순위), 단계별 시간, 버전.
평가 기준과 동일한 계산(D-8b v3 규칙 + D-7 CNN + D-9 v2 RRF)을 그대로 옮긴 것.
"""
import os, re, json, time, unicodedata
import numpy as np, pandas as pd


class PillIdentifier:
    def __init__(self, deploy_dir, device="cpu", load_ocr=True, rotations=None, use_rembg=False):
        t = time.time()
        self.dir = deploy_dir
        self.cfg = json.load(open(f"{deploy_dir}/config.json", encoding="utf-8"))
        self.rot = list(rotations if rotations is not None else self.cfg["ocr"]["rotations"])
        self.use_rembg = use_rembg
        self._load_db()
        self._load_cnn(device)
        self.ocr = self._make_ocr() if load_ocr else None
        self.load_sec = round(time.time() - t, 1)

    # ------------------------------------------------------------ 준비
    def _norm(self, s):
        s = unicodedata.normalize("NFKC", str(s)).upper()
        for w in self.cfg["rule"]["normalize_remove"]: s = s.replace(w, "")
        return re.sub(r"[^0-9A-Z가-힣]", "", s)

    def _load_db(self):
        db = pd.read_csv(f"{self.dir}/{self.cfg['files']['db']}", dtype=str).fillna("")
        self.db = db
        self.SEQ = db["ITEM_SEQ"].to_numpy(); self.IDX = {s: i for i, s in enumerate(self.SEQ)}
        self.SHAPE = db["DRUG_SHAPE"].to_numpy()
        self.COLOR = db["COLOR_CLASS1"].to_numpy() if "COLOR_CLASS1" in db.columns else np.full(len(db), "")
        # 각인 문자열 사전 + 가중치(len+idf)
        self.UP = sorted(set(db["PF"]) | set(db["PB"])); self.UPI = {p: i for i, p in enumerate(self.UP)}
        cnt = pd.concat([db[["ITEM_SEQ", "PF"]].rename(columns={"PF": "p"}), db[["ITEM_SEQ", "PB"]].rename(columns={"PB": "p"})])
        cnt = cnt[cnt.p != ""].drop_duplicates().groupby("p")["ITEM_SEQ"].size()
        n = len(db); floor = self.cfg["rule"]["idf_floor"]
        w_len = np.array([min(1.0, len(p) / 3) for p in self.UP])
        w_idf = np.array([floor + (1 - floor) * np.log(n / (1 + cnt.get(p, 0))) / np.log(n) for p in self.UP])
        self.W = np.sqrt(w_len * w_idf)
        self.fF = db["PF"].map(self.UPI).to_numpy(); self.fB = db["PB"].map(self.UPI).to_numpy()
        lab = np.stack([db[[f"L{k}", f"a{k}", f"b{k}"]].apply(pd.to_numeric, errors="coerce").to_numpy() for k in (1, 2)], 1)
        self.LAB = lab                                   # 품목 × 면(2) × Lab

    def _load_cnn(self, device):
        import torch, torch.nn as nn, torch.nn.functional as F, timm
        self.torch, self.F, self.dev = torch, F, device
        ck = torch.load(f"{self.dir}/{self.cfg['files']['model']}", map_location="cpu", weights_only=False)
        class Net(nn.Module):
            def __init__(s_, name, emb):
                super().__init__()
                s_.bb = timm.create_model(name, pretrained=False, num_classes=0)
                s_.fc = nn.Linear(s_.bb.num_features, emb); s_.bn = nn.BatchNorm1d(emb)
            def forward(s_, x): return F.normalize(s_.bn(s_.fc(s_.bb(x))), dim=1)
        self.net = Net(ck["cfg"]["backbone"], ck["cfg"]["emb"]); self.net.load_state_dict(ck["net"]); self.net.to(device).eval()
        self.S = ck["cfg"]["img"]
        self.GE = torch.from_numpy(np.load(f"{self.dir}/{self.cfg['files']['gallery']}").astype(np.float32)).to(device)
        gi = pd.read_csv(f"{self.dir}/{self.cfg['files']['gallery_index']}", dtype=str)
        faces = gi.groupby("ITEM_SEQ").indices
        self.cfa = np.full(len(self.db), -1); self.cfb = np.full(len(self.db), -1)
        for s, rows in faces.items():
            if s in self.IDX: self.cfa[self.IDX[s]] = rows[0]; self.cfb[self.IDX[s]] = rows[-1]
        self.MEAN = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
        self.STD = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
        self.rot45 = torch.tensor([[[0.7071, -0.7071, 0.0], [0.7071, 0.7071, 0.0]]], device=device)

    def _make_ocr(self):
        from paddleocr import PaddleOCR
        o = self.cfg["ocr"]
        return PaddleOCR(device="cpu", cpu_threads=os.cpu_count(), use_doc_orientation_classify=False,
                         use_doc_unwarping=False, use_textline_orientation=False, lang=o["lang"],
                         text_det_limit_type=o["det_limit_type"], text_det_limit_side_len=o["det_limit_side_len"],
                         text_recognition_batch_size=o["rec_batch"])

    # ------------------------------------------------------------ 전처리
    def _rgba(self, img):
        from PIL import Image
        if isinstance(img, str): img = Image.open(img)
        elif isinstance(img, np.ndarray): img = Image.fromarray(img)
        img = img.convert("RGBA")
        a = np.array(img)[:, :, 3]
        if (a < 250).mean() < 0.01 and self.use_rembg:          # 알파가 없으면(배경 있음) rembg로 제거
            from rembg import remove
            img = remove(img).convert("RGBA")
        return img

    def _align(self, im):
        """알약만 자르기 → 긴 축 가로 정렬 → (흰 배경 RGB, 알파 마스크)"""
        from PIL import Image
        a = np.array(im)[:, :, 3]; ys, xs = np.where(a > 20)
        if len(xs) == 0:
            return im.convert("RGB"), np.full(a.shape, 255, np.uint8)
        im = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)); a = np.array(im)[:, :, 3]; ys, xs = np.where(a > 20)
        vec = np.linalg.eigh(np.cov(np.stack([xs - xs.mean(), ys - ys.mean()])))[1][:, -1]
        ang = np.degrees(np.arctan2(vec[1], vec[0]))
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im)
        rgb = bg.convert("RGB").rotate(ang, expand=True, fillcolor=(255, 255, 255))
        am = Image.fromarray(a).rotate(ang, expand=True, fillcolor=0)
        box = am.point(lambda v: 255 if v > 20 else 0).getbbox()
        return rgb.crop(box), np.array(am.crop(box))

    def _for_ocr(self, rgb):                                   # D-8a와 동일: 10% 여백 + 긴 변 960
        from PIL import Image
        w, h = rgb.size; pad = int(0.10 * max(w, h))
        cv = Image.new("RGB", (w + 2 * pad, h + 2 * pad), (255, 255, 255)); cv.paste(rgb, (pad, pad))
        s = self.cfg["ocr"]["pill_long_side"] / max(cv.size)
        return np.array(cv.resize((round(cv.width * s), round(cv.height * s)), Image.BICUBIC))

    def _for_cnn(self, rgb):                                   # D-7과 동일: 정사각 1.2배 → S
        from PIL import Image
        w, h = rgb.size; m = int(max(w, h) * self.cfg["cnn"]["pad_ratio"])
        cv = Image.new("RGB", (m, m), (255, 255, 255)); cv.paste(rgb, ((m - w) // 2, (m - h) // 2))
        return np.array(cv.resize((self.S, self.S), Image.BICUBIC))

    # ------------------------------------------------------------ 사진 품질(배경 문제) 검사
    QUALITY_MSG = "배경에 문제가 있어 사진을 읽지 못하고 있습니다. 다른 배경(무늬 없는 단색)에서 알약만 보이게 다시 찍어 주세요."
    def quality(self, im):
        """배경 제거 결과로 사진 손상 여부 판단 (경험칙 기준 — 평가 사진 오탐률은 E-5에서 측정)
           no_pill: 알약 영역 없음 / too_large: 배경이 안 지워짐 / border: 알약이 사진 가장자리에 붙음(잘림·배경 포함)
           fragmented: 조각이 여러 개(무늬 배경 잔여물) / low_solidity: 윤곽이 울퉁불퉁(배경과 섞임·손상)"""
        import cv2
        a = (np.array(im)[:, :, 3] > 20).astype(np.uint8); H, W = a.shape; area = a.mean()
        issues = []
        if area < 0.005: return dict(ok=False, issues=["no_pill"], message=self.QUALITY_MSG)
        if area > 0.85: issues.append("too_large")
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]).mean()
        if edge > 0.20: issues.append("border")
        n, lab, st, _ = cv2.connectedComponentsWithStats(a, 8)
        big = st[1:, cv2.CC_STAT_AREA]; main = big.max()
        if main / big.sum() < 0.80: issues.append("fragmented")
        cnt, _ = cv2.findContours((lab == 1 + big.argmax()).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = cv2.contourArea(cv2.convexHull(cnt[0]))
        if hull > 0 and main / hull < 0.85: issues.append("low_solidity")
        return dict(ok=not issues, issues=issues, message=self.QUALITY_MSG if issues else "")

    # ------------------------------------------------------------ 단계별 계산
    def read_text(self, arr):
        """OCR: 방향별 읽기 → (정규화 글자 집합, 원본 읽기)"""
        raw = []
        for r in self.rot:
            res = self.ocr.predict(np.ascontiguousarray(np.rot90(arr, r // 90)[:, :, ::-1]))[0]
            raw.append(dict(rot=r, texts=list(res["rec_texts"]), scores=[float(x) for x in res["rec_scores"]]))
        return self.texts_from_reads(raw), raw

    def texts_from_reads(self, reads):
        o = self.cfg["ocr"]; out = set()
        for r in reads:
            if r["rot"] not in self.rot: continue
            good = [t for t in (self._norm(x) for x, sc in zip(r["texts"], r["scores"]) if sc >= o["min_score"])
                    if t and not (o["drop_single_hangul"] and re.fullmatch(r"[가-힣]", t))]
            out |= set(good)
            if len(good) > 1: out.add("".join(good))
        return sorted(out)

    def _sim(self, texts):
        from rapidfuzz.process import cdist
        from rapidfuzz.distance import Indel
        v = np.zeros(len(self.UP))
        if texts:
            m = cdist(self.UP, texts, scorer=Indel.normalized_similarity, workers=-1); sub = np.zeros_like(m)
            for j, t in enumerate(texts):
                if len(t) < 2: continue
                for i, p in enumerate(self.UP):
                    if len(p) >= 2:
                        if p in t: sub[i, j] = 0.95 * len(p) / len(t)
                        elif t in p: sub[i, j] = 0.9 * len(t) / len(p)
            v = np.maximum(m, sub).max(1) * self.W
        e = self.cfg["rule"]["empty_print_score"]
        if "" in self.UPI: v[self.UPI[""]] = e["text"] if texts else e["no_text"]
        return v

    def _lab(self, im):                                        # D-8b와 동일: 원본 RGBA의 알약 픽셀(가장자리 7px 제외) 평균 Lab
        import cv2
        a = np.array(im)
        m = cv2.erode((a[:, :, 3] > 20).astype(np.uint8), np.ones((7, 7)))
        px = cv2.cvtColor(np.ascontiguousarray(a[:, :, :3]), cv2.COLOR_RGB2LAB)[m > 0]
        if len(px) == 0: return np.full(3, np.nan)
        lab = px.mean(0)
        return lab if self.cfg["rule"]["lab_scale"] == "opencv_0_255" else np.array([lab[0] * 100 / 255, lab[1] - 128, lab[2] - 128])

    def cnn_sims(self, arr):
        """8방향 TTA → 갤러리 면별 최대 유사도"""
        torch, F = self.torch, self.F
        with torch.no_grad():
            x = torch.from_numpy(arr).to(self.dev).permute(2, 0, 1).float()[None] / 255
            x45 = F.grid_sample(x - 1, F.affine_grid(self.rot45, x.shape, align_corners=False), align_corners=False) + 1
            xs = torch.cat([torch.rot90(x, k, (2, 3)) for k in range(4)] + [torch.rot90(x45, k, (2, 3)) for k in range(4)])
            e = self.net((xs - self.MEAN) / self.STD)
            return (e @ self.GE.T).max(0).values.cpu().numpy()

    @staticmethod
    def _ranks(s, ok):
        from scipy.stats import rankdata
        r = np.full(len(s), 10 ** 6, dtype=float); idx = np.where(ok)[0]
        r[idx] = rankdata(-s[idx], method="max"); return r

    # ------------------------------------------------------------ 메인
    def prepare(self, img, reads=None):
        """사진 1장 → OCR 글자, 색, CNN 유사도 (reads를 주면 OCR 생략: 저장된 결과 재사용·테스트용)"""
        T = {}; t = time.time()
        im = self._rgba(img); q = self.quality(im); rgb, mask = self._align(im); T["prep"] = time.time() - t; t = time.time()
        if reads is None:
            texts, reads = self.read_text(self._for_ocr(rgb))
        else:
            texts = self.texts_from_reads(reads)
        T["ocr"] = time.time() - t; t = time.time()
        lab = self._lab(im)
        sims = self.cnn_sims(self._for_cnn(rgb)); T["cnn"] = time.time() - t
        return dict(texts=texts, reads=reads, lab=lab, sims=sims, t=T, quality=q)

    def analyze(self, front, back, shape=None, top_k=5, front_reads=None, back_reads=None, _prepared=None, color=None,
                return_prepared=False):
        """color: 사용자가 답한 색(식약처 분류, 예: '하양') — 각인 없는 약 경로에서 필터로 사용"""
        t0 = time.time()
        A = _prepared[0] if _prepared else self.prepare(front, front_reads)
        B = _prepared[1] if _prepared else self.prepare(back, back_reads)
        sa, sb = self._sim(A["texts"]), self._sim(B["texts"])
        ocr = np.maximum(sa[self.fF] + sb[self.fB], sa[self.fB] + sb[self.fF]) / 2
        d1 = np.linalg.norm(self.LAB[:, 0] - A["lab"], axis=1) + np.linalg.norm(self.LAB[:, 1] - B["lab"], axis=1)
        d2 = np.linalg.norm(self.LAB[:, 1] - A["lab"], axis=1) + np.linalg.norm(self.LAB[:, 0] - B["lab"], axis=1)
        col = np.nan_to_num(np.minimum(d1, d2) / 2, nan=200)
        rule = ocr - self.cfg["rule"]["color_lambda"] * col / 100
        a, b = A["sims"], B["sims"]
        cnn = np.where(self.cfa >= 0, np.maximum(a[self.cfa] + b[self.cfb], a[self.cfb] + b[self.cfa]) / 2, -9)
        ok = (self.SHAPE == shape) if shape else np.ones(len(rule), bool)
        if shape and ok.sum() == 0: ok = np.ones(len(rule), bool)              # 모르는 모양 값이면 필터 없이
        if color:
            okc = ok & (self.COLOR == color)
            if okc.sum() > 0: ok = okc
        fu = self.cfg["fusion"]; rr, rc = self._ranks(rule, ok), self._ranks(cnn, ok)
        score = np.where(ok, 1 / (fu["k"] + rr) + fu["w_cnn"] / (fu["k"] + rc), -1)
        order = np.argsort(-score, kind="stable")[:top_k]
        cands = []
        for n, i in enumerate(order, 1):
            r = self.db.iloc[i]
            cands.append(dict(rank=n, item_seq=r["ITEM_SEQ"], name=r.get("ITEM_NAME", ""), company=r.get("ENTP_NAME", ""),
                              print_front=r["PRINT_FRONT"], print_back=r["PRINT_BACK"], shape=r["DRUG_SHAPE"],
                              color=r.get("COLOR_CLASS1", ""), etc_otc=r.get("ETC_OTC_NAME", ""),
                              score=round(float(score[i]), 4), rule_rank=int(rr[i]), cnn_rank=int(rc[i]),
                              rule_score=round(float(rule[i]), 3), cnn_score=round(float(cnn[i]), 3)))
        s1, s2 = (score[order[0]], score[order[1]]) if len(order) > 1 else (score[order[0]], 0)
        out = dict(
            query=dict(shape=shape, ocr_front=A["texts"], ocr_back=B["texts"]),
            quality=dict(front=A.get("quality"), back=B.get("quality"),
                         ok=bool((A.get("quality") or {}).get("ok", True) and (B.get("quality") or {}).get("ok", True))),
            candidates=cands,
            ambiguous=bool((s1 - s2) / max(s1, 1e-9) < 0.10),                  # 1·2위 차이 10% 미만 → 선택지 제시 권장(경험칙, 미검증)
            timing_sec={k: round(A["t"][k] + B["t"][k], 2) for k in A["t"]} | {"total": round(time.time() - t0, 2)},
            version=dict(config=self.cfg["version"], cnn=self.cfg["cnn"]["tag"], fusion=f"rrf k{fu['k']} w{fu['w_cnn']}",
                         ocr_rotations=self.rot))
        out["band"], out["imprint_match"] = self._band(cands[0] if cands else None, A["texts"], B["texts"])
        if return_prepared: out["_prepared"] = (A, B)          # 세션에 보관 → 각인 입력·색 선택 후 재검색에 사용 (JSON 아님)
        return out

    # ------------------------------------------------------------ 대화 흐름 (최종 v4, 문장은 전부 코드 템플릿)
    MSG = {
        "top1": "사진과 가장 일치하는 약입니다. 가지고 계신 약과 같은지 사진으로 확인해 주세요.",
        "top3": "비슷한 약 3개를 찾았습니다. 가지고 계신 약을 골라 주세요.",
        "ask_imprint": "약의 각인(새겨진 글자)을 확인하지 못했습니다. 각인이 있다면 입력해 주세요.",
        "ask_color": "약의 색을 골라 주세요.",
        "retake": "확인에 실패했습니다. 다시 촬영해 주세요.",
        "give_up": "사진을 통해 약에 대한 정보를 찾을 수 없습니다. 정확한 정보와 상담은 약사를 통해 문의 바랍니다.",
        "caution": "사진만으로는 오인식될 수 있습니다. 복용 전 약 봉투·처방전을 확인하거나 약사에게 문의하세요.",
        "storage": "처방전·약봉투 등 개인정보가 담긴 사진은 저장되지 않습니다. 알약 사진은 배경을 제거한 알약 부분만 저장됩니다.",
    }
    BUTTONS = {"top1": ["네", "아니오"], "top3": ["(후보 선택)", "목록에 없음"],
               "ask_imprint": ["(각인 입력)", "글자 대신 그림(로고)이 있어요", "각인이 없어요"]}

    def _band(self, c, ta, tb):
        """1위 후보의 각인 일치도(0~1) → 밴드 A/B/C/D, 각인 없는 후보면 E"""
        from rapidfuzz.distance import Indel
        if c is None: return "D", 0.0
        ps = [p for p in (self._norm(c["print_front"]), self._norm(c["print_back"])) if p]
        if not ps: return "E", None
        reads = sorted(set(ta) | set(tb))
        m = float(np.mean([max(Indel.normalized_similarity(p, t) for t in reads) for p in ps])) if reads else 0.0
        return ("A" if m >= 0.9 else "B" if m >= 0.8 else "C" if m >= 0.6 else "D"), round(m, 3)

    def next_step(self, res, attempt=1):
        """analyze 결과 → 화면에 보낼 다음 단계 (흐름 v4)
           A: 1위 제공(+확인) / B·C·D: Top-3 / E: 각인 입력 요청 먼저 / 사진 품질 문제: 재촬영 안내"""
        if not res.get("quality", {}).get("ok", True):
            return dict(step="quality", message=self.QUALITY_MSG, caution=self.MSG["caution"])
        b = res["band"]
        if b == "A": step, cands = "top1", res["candidates"][:1]
        elif b == "E": step, cands = "ask_imprint", []
        else: step, cands = "top3", res["candidates"][:3]
        return dict(step=step, band=b, imprint_match=res["imprint_match"], message=self.MSG[step],
                    buttons=self.BUTTONS.get(step, []), candidates=cands, caution=self.MSG["caution"])

    def on_reject(self, attempt, from_step=None, res=None):
        """[아니오]/[목록에 없음] 이후
           A의 1위에 [아니오] → Top-3 먼저 / 그 외 1회차 → 각인 입력 요청(텍스트 우선) / 각인 입력 후에도 실패 → 재촬영(1회) → 종료"""
        if from_step == "top1" and res is not None:
            return dict(step="top3", message=self.MSG["top3"], buttons=self.BUTTONS["top3"], candidates=res["candidates"][:3],
                        caution=self.MSG["caution"])
        if attempt == 1: return dict(step="ask_imprint", message=self.MSG["ask_imprint"], buttons=self.BUTTONS["ask_imprint"])
        if attempt == 2: return dict(step="retake", message=self.MSG["retake"])
        return dict(step="give_up", message=self.MSG["give_up"])

    def refine(self, prepared, shape=None, imprint_front=None, imprint_back=None, color=None, top_k=3):
        """사용자 입력으로 재검색: 각인 입력(앞→사진1, 뒤→사진2) 또는 색 선택(로고·각인 없음 경로). 사진 재처리 없음"""
        A, B = prepared
        mk = lambda t: self.texts_from_reads([dict(rot=self.rot[0], texts=[t], scores=[1.0])]) if t and self._norm(t) else []
        if imprint_front is not None or imprint_back is not None:
            A, B = dict(A, texts=mk(imprint_front)), dict(B, texts=mk(imprint_back))
        r = self.analyze(None, None, shape=shape, top_k=top_k, _prepared=(A, B), color=color)
        return dict(step="top3", message=self.MSG["top3"], buttons=self.BUTTONS["top3"], candidates=r["candidates"][:3],
                    caution=self.MSG["caution"])

    def on_imprint_choice(self, choice):
        """각인 입력 화면의 버튼: 로고·각인 없음 → 색 선택(모양은 처음 버튼으로 입력됨)"""
        if choice in ("글자 대신 그림(로고)이 있어요", "각인이 없어요"):
            return dict(step="ask_color", message=self.MSG["ask_color"], buttons=self.color_options())
        return None

    def color_options(self):
        return sorted(c for c in set(self.COLOR) if c)

    @staticmethod
    def handoff(candidate, user_question=""):
        """사용자가 확인한 약 → LLM·RAG로 넘기는 값 (item_seq 우선 키 + name)"""
        return dict(item_seq=candidate["item_seq"], name=candidate["name"], company=candidate.get("company", ""),
                    confirmed_by_user=True, user_question=user_question)

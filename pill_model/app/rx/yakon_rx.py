"""
yakon_rx.py — 약ON 처방전·약봉투 읽기 모듈 (OCR → 개인정보 차단 → LLM 구조화 → DB 매칭 → 숫자 검증)

노트북 'OCR 모델링' 최종 셀을 그대로 옮긴 것 (계산을 바꾸지 않음):
  R-2a  OCR 입력 준비(load_img)·PaddleOCR (CPU 최종: server_det · 검출 1280 · 인식 배치 16, R-4 준비)
  R-2b  개인정보 3중 차단(build_prompt) + Haiku 4.5 프롬프트 V2(call_llm)
  R-2c  이름 정규화 v4(unit/key/base) · 중복 제거(dedupe) · DB 매칭(db_match) · 숫자 화면 구간(ui_tier)
  R-2f  함량 Plan B(db_match_v4) · 1회량 형식 검증(dose_unit/dose_ok_format) · 위치 검증(band)
  R-2g  최종 규칙 A+C (CONF_STRENGTH 0.80, dose_only_count v5, 후보: 함량 선택=형제 전체 / 그 외 Top-3)
  R-2h  용법 상한 검증(근거 문장 포함) — 이름이 확정된 약에만 (B-ALL의 상한표는 미리 계산해 dose_envelope.json으로)

사용 예:
    from yakon_rx import RxReader
    rx = RxReader("/path/to/deploy/rx")              # OCR·LLM 모두 준비
    out = rx.analyze("rx_0001.jpg")                  # 사진 → 약 목록(판정·후보·숫자 화면 구간)
    rx.confirm(out["drugs"][0], item_seq="2012…")    # 사용자가 이름을 확정하면 → 용법 상한 검증 반영

개인정보: 사진·OCR 글자·LLM 입력은 이 모듈이 저장하지 않는다. LLM에는 차단·가림을 통과한 약 관련 줄만 보낸다.
"""
import os, re, json, time
import numpy as np, pandas as pd

# ───────────────────────────── R-2b: 프롬프트 V2 · 개인정보 차단 (원문 그대로)
SYSTEM_V2 = """너는 한국 처방전·약봉투의 OCR 줄을 표 형식으로 옮겨 적는 도구다. 판단하거나 고치지 않는다.
규칙:
1. 입력은 '[번호] 글자' 형식의 OCR 줄이다. 줄에 없는 글자는 절대 만들지 않는다.
2. 약품마다 추출:
   - name: 약품명을 줄에 적힌 글자 그대로 복사한다. 괄호 안 성분명·규격·'수출용'까지 모두 포함한다.
           오타처럼 보여도 고치지 않는다. 앞의 순번('01.')과 용량·횟수·일수만 뺀다.
   - dose: 1회 투약량 (예: '2정', '15mL', '1포') / times: 1일 투여 횟수 / days: 총 투약 일수
   - 각 값이 나온 줄 번호: name_line, dose_line, times_line, days_line
3. 약봉투의 '1회 2정 · 하루 2회 · 7일'에서 '1회'는 횟수가 아니다 → dose='2정', times=2, days=7.
4. 숫자는 줄에 적힌 그대로 옮긴다. 상식에 맞지 않아 보여도(예: 13회) 그대로 옮긴다. 판단은 이후 단계가 한다.
5. 줄에서 값을 찾을 수 없을 때만 값과 줄 번호를 null 로 둔다.
6. 개인정보와 [주민번호]·[전화]·[날짜] 가림 표시, 복용 시간 체크, 효능 문장은 출력하지 않는다.
7. 출력은 설명 없이 JSON 하나만:
{"doc_type": "prescription|medicine_bag|unknown", "drugs": [{"name": "", "name_line": 0, "dose": "", "dose_line": 0, "times": 0, "times_line": 0, "days": 0, "days_line": 0}]}"""

BLOCK_KW = re.compile(r"환자|성명|이름|주민|생년월일|생일|연락처|전화|휴대|주소|보험|가입자|"
                      r"의료기관|병원|의원|기관기호|의사|의료인|면허|약국|약사|처방전\s*번호|교부번호|발행일|조제일|"
                      r"복용\s*시간|아침|점심|저녁|취침")
ALLOW = re.compile(r"\d+(?:\.\d+)?\s*(?:정|캡슐|mL|ml|포|회|일|방울|회분)|"
                   r"(?:정|캡슐|캡|시럽|액|산|연질|서방|주|크림|겔|패치|점안|가글)(?:\(|$|\s|\d)|"
                   r"밀리그|마이크로그|mg|약품명|제품명|처방\s*의약품|1회|1일|복용|투약")
PATTERNS = [(re.compile(r"\d{6}\s*-\s*[1-4]\d{6}"), "[주민번호]"),
            (re.compile(r"01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}"), "[전화]"),
            (re.compile(r"0\d{1,2}\s*-\s*\d{3,4}\s*-\s*\d{4}"), "[전화]"),
            (re.compile(r"(19|20)\d{2}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?"), "[날짜]")]

# ───────────────────────────── R-2c: 이름 정규화 v4 (원문 그대로)
UNIT = [(r"[밀일열]리그[람램럼첨]", "mg"),
        (r"㎎", "mg"), (r"마이크로그람|마이크로그램|㎍|μg|µg", "mcg"),
        (r"밀리리터|㎖", "ml"), (r"(?<![a-z])그람|그램", "g"), (r"mL|ML", "ml")]
PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]")
STRENGTH = re.compile(r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)*(?:mg|mcg|ml|g|%)(?:/ml)?")
SYM = r"[*#_\-·.~]+"


def unit(s):
    s = re.sub(r"\s+", "", str(s))
    s = re.sub(rf"^{SYM}|{SYM}$", "", s)
    for a, b in UNIT:
        s = re.sub(a, b, s)
    return re.sub(r"캡$", "캡슐", s.lower())


def key(s):
    s = PAREN.sub("", unit(s))
    s = re.sub(r"[\(\[].*$", "", s)
    return re.sub(rf"{SYM}$", "", s)


def base(s): return STRENGTH.sub("", key(s))
def allowed_errors(n): return 0 if n <= 6 else (1 if n <= 14 else 2)


def dedupe(pred):
    """같은 문서에서 이름·1회량·횟수·일수가 모두 같은 약은 하나만 남김"""
    seen, out = set(), []
    for p in pred:
        sig = (key(p.get("name", "")), str(p.get("dose")), str(p.get("times")), str(p.get("days")))
        if sig[0] and sig in seen: continue
        seen.add(sig); out.append(p)
    return out


def norm(s): return re.sub(r"\s+", "", str(s))
def line_of(lines, i): return lines[i] if isinstance(i, int) and 0 <= i < len(lines) else None


def num(s):
    m = re.search(r"\d+(?:\.\d+)?", str(s)); return float(m.group()) if m else None


def unit_of(s):
    m = re.search(r"[가-힣a-zA-Z]+", re.sub(r"[\d.\s]", "", str(s))); return m.group().lower() if m else ""


def to_rows(lines):
    bx = []
    for i, l in enumerate(lines):
        ys = [p[1] for p in l["poly"]]; xs = [p[0] for p in l["poly"]]
        bx.append({**l, "id": i, "yc": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys), "x0": min(xs)})
    bx.sort(key=lambda b: b["yc"]); rows = []
    for b in bx:
        if rows and abs(b["yc"] - rows[-1][-1]["yc"]) < max(b["h"], rows[-1][-1]["h"]) * 0.5: rows[-1].append(b)
        else: rows.append([b])
    return [sorted(r, key=lambda b: b["x0"]) for r in rows]


def to_rows_ids(lines):
    """R-2b: OCR 조각들을 세로 위치로 묶어 '한 줄(행)'로 만듦 → 행 단위로 차단 판단"""
    bx = []
    for i, l in enumerate(lines):
        ys = [p[1] for p in l["poly"]]; xs = [p[0] for p in l["poly"]]
        bx.append({"id": i, "text": l["text"], "yc": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys), "x0": min(xs)})
    bx.sort(key=lambda b: b["yc"]); rows = []
    for b in bx:
        if rows and abs(b["yc"] - rows[-1][-1]["yc"]) < max(b["h"], rows[-1][-1]["h"]) * 0.5: rows[-1].append(b)
        else: rows.append([b])
    return [sorted(r, key=lambda b: b["x0"]) for r in rows]


def build_prompt(lines):
    """개인정보 3중 차단: ① 막을 단어가 있는 줄 제외 ② 약 신호가 없는 줄 제외 ③ 남은 줄의 번호 패턴 가림
       → (LLM에 보낼 글, 제외한 OCR 줄 번호, 가린 개수)"""
    keep, dropped, n_mask = [], [], 0
    for r in to_rows_ids(lines):
        t = " ".join(b["text"] for b in r)
        if BLOCK_KW.search(t) or not ALLOW.search(t):
            dropped += [b["id"] for b in r]; continue
        nr = []
        for b in r:
            s = b["text"]
            for pat, rep in PATTERNS:
                s, c = pat.subn(rep, s); n_mask += c
            nr.append(f"[{b['id']}] {s}")
        keep.append(" | ".join(nr))
    return "OCR 줄:\n" + "\n".join(keep), dropped, n_mask


# ───────────────────────────── R-2f · R-2g: 숫자 검증 도구 (원문 그대로)
FORM = {"정", "캡슐", "ml", "포", "방울", "회분", "개", "매", "스푼", "앰플", "병"}
UNIT_FIX = [(r"청$", "정"), (r"캡[슬술]$", "캡슐"), (r"m[l니I1]?$", "ml"), (r"ml$", "ml")]


def dose_unit(s):
    u = re.sub(r"[\d.\s\[\]()]", "", str(s)).lower()
    for a, b in UNIT_FIX:
        u = re.sub(a, b, u)
    return u


def dose_ok_format(val):
    s = str(val)
    if re.search(r"mg|㎎|밀리|그램|/", s, re.I): return False
    u = dose_unit(s)
    return u == "" or u in FORM


def ycenter(line):
    ys = [p[1] for p in line["poly"]]; return (min(ys) + max(ys)) / 2


def dose_only_count(val, text):
    """v5: 1회량이 단위 없는 숫자이고, 그 줄에서 이 숫자가 '회'나 '일' 앞에만 나오면 True"""
    s = str(val).strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", s): return False
    ends = [m.end() for m in re.finditer(rf"(?<![\d.]){re.escape(s)}(?![\d.])", text)]
    return bool(ends) and all(re.match(r"\s*(회|일)", text[e:]) for e in ends)


# ───────────────────────────── 화면 문구 (코드 고정, LLM 생성 아님)
UI_TEXT = {
    "notice": "자동 인식 결과는 틀릴 수 있어요. 저장 전에 반드시 직접 확인해 주세요.",
    "storage": "처방전·약봉투 사진과 읽은 글자는 저장되지 않습니다.",
}


class RxReader:
    def __init__(self, deploy_dir, ocr=None, llm_client=None, load_ocr=True, load_llm=True):
        """deploy_dir: config_rx.json · permit_names.csv · dose_envelope.json 이 있는 폴더
           ocr: 이미 만든 PaddleOCR(알약 모듈과 공유할 때). 없으면 load_ocr=True일 때 새로 만듦
           llm_client: boto3 bedrock-runtime 클라이언트. 없으면 load_llm=True일 때 새로 만듦(EC2는 IAM 역할, Colab은 Bearer 키)"""
        t = time.time()
        self.dir = deploy_dir
        self.cfg = json.load(open(f"{deploy_dir}/config_rx.json", encoding="utf-8"))
        r = self.cfg["rule"]
        self.CONF_AUTO, self.CONF_LOW, self.CONF_STRENGTH, self.MARGIN = r["conf_auto"], r["conf_low"], r["conf_strength"], r["margin"]
        self.RANGE = {k: tuple(v) for k, v in r["range"].items()}
        self.AUTO_V4 = set(r["auto_decisions"])
        self.TOL, self.UMAP = r["dose_tol"], r["umap"]
        self._load_db()
        self.env = json.load(open(f"{deploy_dir}/{self.cfg['files']['dose_envelope']}", encoding="utf-8"))
        self.ocr = ocr if ocr is not None else (self._make_ocr() if load_ocr else None)
        self.llm = llm_client if llm_client is not None else (self._make_llm() if load_llm else None)
        self.load_sec = round(time.time() - t, 1)

    # ------------------------------------------------------------ 준비
    def _load_db(self):
        from rapidfuzz.distance import Levenshtein  # noqa: F401  (설치 확인용)
        DBM = pd.read_csv(f"{self.dir}/{self.cfg['files']['permit_names']}", dtype=str).fillna("")
        DBM = DBM[["ITEM_SEQ", "ITEM_NAME", "CANCEL_NAME"]].drop_duplicates("ITEM_SEQ").copy()
        DBM["u"] = DBM["ITEM_NAME"].map(unit); DBM["k"] = DBM["ITEM_NAME"].map(key); DBM["b"] = DBM["ITEM_NAME"].map(base)
        self.u2seq = DBM.groupby("u")["ITEM_SEQ"].apply(list).to_dict()
        self.k2seq = DBM.groupby("k")["ITEM_SEQ"].apply(list).to_dict()
        self.b2seq = DBM.groupby("b")["ITEM_SEQ"].apply(list).to_dict()
        self.seq2k = DBM.set_index("ITEM_SEQ")["k"].to_dict(); self.seq2b = DBM.set_index("ITEM_SEQ")["b"].to_dict()
        self.seq2st = DBM.set_index("ITEM_SEQ")["CANCEL_NAME"].to_dict()
        self.seq2name = DBM.set_index("ITEM_SEQ")["ITEM_NAME"].to_dict()
        self.kkeys = list(self.k2seq.keys())

    def _make_ocr(self):
        from paddleocr import PaddleOCR
        o = self.cfg["ocr"]
        return PaddleOCR(lang=o["lang"], device="cpu", cpu_threads=os.cpu_count(),
                         text_det_limit_type=o["det_limit_type"], text_det_limit_side_len=o["det_limit_side_len"],
                         text_recognition_batch_size=o["rec_batch"], use_doc_orientation_classify=False,
                         use_doc_unwarping=False, use_textline_orientation=False)

    def _make_llm(self):
        import boto3
        return boto3.client("bedrock-runtime", region_name=self.cfg["llm"]["region"])

    # ------------------------------------------------------------ R-2a: 사진 → OCR 줄
    def load_img(self, img):
        from PIL import Image, ImageOps
        max_side = self.cfg["ocr"]["max_side"]
        if isinstance(img, (bytes, bytearray)):
            import io; img = io.BytesIO(img)                               # 서버: S3에서 받은 바이트 그대로
        im = Image.open(img) if isinstance(img, (str, os.PathLike)) or hasattr(img, "read") else img
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size; s = min(1.0, max_side / max(w, h))
        if s < 1: im = im.resize((int(w * s), int(h * s)))
        return np.array(im)[:, :, ::-1].copy(), im.size

    def read_lines(self, img, per_call_limit=None):
        """per_call_limit=True: 공유 엔진(알약용 640으로 생성)에서 이 호출만 1280으로 검출 (R-E3에서 동일성 확인 후 사용)"""
        arr, size = self.load_img(img)
        o = self.cfg["ocr"]; t0 = time.time()
        if per_call_limit if per_call_limit is not None else o.get("per_call_limit", False):
            res = self.ocr.predict(arr, text_det_limit_type=o["det_limit_type"], text_det_limit_side_len=o["det_limit_side_len"])[0]
        else:
            res = self.ocr.predict(arr)[0]
        lines = [{"text": t, "score": float(s), "poly": np.asarray(p).tolist()}
                 for t, s, p in zip(res["rec_texts"], res["rec_scores"], res["rec_polys"])]
        return lines, dict(size=size, ocr_sec=round(time.time() - t0, 2))

    # ------------------------------------------------------------ R-2b: LLM 구조화
    def call_llm(self, prompt):
        L = self.cfg["llm"]
        for a in range(L["retries"] + 1):
            t0 = time.time()
            r = self.llm.converse(modelId=L["model_id"], system=[{"text": SYSTEM_V2}],
                                  messages=[{"role": "user", "content": [{"text": prompt}]}],
                                  inferenceConfig={"maxTokens": L["max_tokens"], "temperature": L["temperature"]})
            text = r["output"]["message"]["content"][0]["text"]
            try:
                s, e = text.find("{"), text.rfind("}")
                return json.loads(text[s:e + 1]), r["usage"], time.time() - t0, text
            except Exception:
                if a == L["retries"]: return None, r["usage"], time.time() - t0, text
                time.sleep(1)

    # ------------------------------------------------------------ R-2c · R-2f: DB 매칭
    def db_match(self, q, conf):
        """약 이름 → (판정, 1위 item_seq, 사용자에게 보여줄 후보 목록, 찾은 방법)"""
        from rapidfuzz import process
        from rapidfuzz.distance import Levenshtein
        u2seq, k2seq, b2seq, seq2k, seq2b, kkeys = self.u2seq, self.k2seq, self.b2seq, self.seq2k, self.seq2b, self.kkeys
        q = re.sub(r"^\d+\.\s*", "", str(q or "")); c = conf or 0
        if not key(q):
            return "매칭 실패(직접 검색)", None, [], "-"
        u, k, b = unit(q), key(q), base(q)
        exact, how = None, None
        if u in u2seq and len(u2seq[u]) == 1: exact, how = u2seq[u][0], "① 전체"
        elif k in k2seq:
            if len(k2seq[k]) == 1: exact, how = k2seq[k][0], "② 괄호제외"
            else: return "확인 필요(같은 이름 여러 품목)", k2seq[k][0], k2seq[k], "② 다중"
        if exact:
            sibs = b2seq.get(seq2b[exact], [exact])
            near = [k2seq[n][0] for n, d, _ in process.extract(seq2k[exact], kkeys, scorer=Levenshtein.distance, limit=4)
                    if n != seq2k[exact] and d <= 1]
            if c < self.CONF_STRENGTH:
                return ("함량 선택", exact, sibs, how) if len(sibs) > 1 else ("확인 필요", exact, [exact] + near, how)
            if len(sibs) > 1: return "함량 자동입력(배지)", exact, [exact], how
            if near:          return "자동 입력(유사이름 배지)", exact, [exact], how
            return "자동 배치", exact, [exact], how
        if b in b2seq and len(b2seq[b]) > 1:
            return "함량 선택", b2seq[b][0], b2seq[b], "③ 함량누락"
        if len(k) >= 4:
            pre = [n for n in kkeys if n.startswith(k)] or [n for n in kkeys if len(n) >= 4 and k.startswith(n)]
            if pre:
                pre = sorted(pre, key=lambda n: abs(len(n) - len(k)))[:3]
                return "확인 필요(앞부분 일치)", k2seq[pre[0]][0], [k2seq[n][0] for n in pre], "④ 앞부분"
        cands = process.extract(k, kkeys, scorer=Levenshtein.distance, limit=5)
        (top, d1, _), d2 = cands[0], cands[1][1]
        if d1 / max(len(k), 1) > 0.3:
            return "매칭 실패(직접 검색)", None, [], "⑤ 실패"
        tseq = k2seq[top][0]
        if c >= self.CONF_AUTO and d1 <= allowed_errors(len(top)) and d2 - d1 >= self.MARGIN and len(b2seq.get(seq2b[tseq], [])) == 1:
            return "자동 배치", tseq, [tseq], "⑤ 오타"
        return "확인 필요", tseq, [k2seq[n][0] for n, _, _ in cands[:3]], "⑤ 오타"

    def db_match_v4(self, q, conf):
        dec, top, opts, how = self.db_match(q, conf)
        if dec == "함량 자동입력(배지)":                  # Plan B: 형제 있으면 항상 사용자 선택
            return "함량 선택", top, self.b2seq.get(self.seq2b[top], [top]), how
        return dec, top, opts, how

    def ui_tier(self, conf, v, key_):
        if v is None or conf is None or conf < self.CONF_LOW: return "빈칸"
        if key_ in self.RANGE:
            lo, hi = self.RANGE[key_]
            if not (lo <= v <= hi): return "확인 필요(범위 밖)"
        return "미리 채움" if conf >= self.CONF_AUTO else "확인 필요"

    # ------------------------------------------------------------ R-2g: 한 문서의 약 목록 판정 (정답 없이)
    def decide(self, lines, llm_result, apply_confirm=True):
        """LLM 결과 + OCR 줄 → 약마다 (이름 판정·후보, 숫자 3개의 값·확신도·화면 구간). R-2g 계산과 동일
           반환 목록의 순서 = dedupe(LLM 약 목록) 순서. apply_confirm=False면 자동 입력 약에도 용법 상한 검증을 아직 안 붙임(검증용)"""
        pred = dedupe((llm_result or {}).get("drugs", []) or [])
        ys = sorted({ycenter(lines[p["name_line"]]) for p in pred if line_of(lines, p.get("name_line"))})

        def band(p):
            ln = line_of(lines, p.get("name_line"))
            if not ln: return None
            y0 = ycenter(ln); h = max(q[1] for q in ln["poly"]) - min(q[1] for q in ln["poly"])
            nxt = [y for y in ys if y > y0 + h * 0.5]
            return (y0 - h * 0.6, (min(nxt) - h * 0.5) if nxt else 1e9)

        drugs = []
        for p in pred:
            ln = line_of(lines, p.get("name_line"))
            dec, top, opts, how = self.db_match_v4(p.get("name"), ln["score"] if ln else None)
            shown = opts if dec == "함량 선택" else (opts or [])[:3]          # 함량 선택은 형제 전체, 나머지는 Top-3
            auto = dec in self.AUTO_V4
            bd = band(p)
            fields = {}
            for key_ in ["dose", "times", "days"]:
                val = p.get(key_)
                v = num(val) if val is not None else None
                ln2 = line_of(lines, p.get(f"{key_}_line"))
                conf = ln2["score"] if ln2 else None
                digits = re.sub(r"\D", "", str(val)) if val is not None else ""
                grounded = val is None or (ln2 is not None and digits != "" and digits in re.sub(r"\D", "", ln2["text"]))
                in_band = ln2 is None or bd is None or (bd[0] <= ycenter(ln2) <= bd[1])
                ui = "확인 필요(근거 없음)" if not grounded else self.ui_tier(conf, v, key_)
                if ui == "미리 채움":
                    if not in_band: ui = "확인 필요(위치)"
                    elif key_ == "dose" and (not dose_ok_format(val) or dose_only_count(val, ln2["text"])):
                        ui = "확인 필요(형식)"
                fields[key_] = dict(value=val, conf=None if conf is None else round(conf, 4), ui=ui)
            d = dict(name_read=p.get("name"), name_conf=None if not ln else round(ln["score"], 4),
                     decision=dec, how=how, auto=auto, item_seq=top if auto else None,
                     candidates=[dict(item_seq=s, item_name=self.seq2name.get(s, ""), status=self.seq2st.get(s, ""))
                                 for s in shown],
                     fields=fields)
            if auto and apply_confirm:                                    # 자동 입력이면 바로 용법 상한 검증
                d = self.confirm(d, top)
            drugs.append(d)
        return drugs

    # ------------------------------------------------------------ R-2h: 이름 확정 후 용법 상한 검증
    def env_of(self, seq):
        e = self.env.get(str(seq))
        return (e["d"], e["ds"], e["t"], e["ts"]) if e else ({}, {}, None, "")

    def over_check(self, seq, field, pred):
        """(상한 초과 여부, 근거 문장) — R-2h over_label과 동일 (path 조건은 confirm 호출 자체로 충족)"""
        v = num(pred) if pred is not None else None
        if not seq or v is None: return False, ""
        d, ds, t, ts = self.env_of(seq)
        if field == "dose":
            u = self.UMAP.get(dose_unit(pred), dose_unit(pred))
            if not u: u = next(iter(d)) if len(d) == 1 else ""
            return (u in d and v > d[u] * self.TOL), ds.get(u, "")
        if field == "times":
            return (t is not None and v > t * self.TOL), ts
        return False, ""

    def confirm(self, drug, item_seq):
        """사용자가 이름을 확정(자동 입력 또는 후보 탭)했을 때 → 숫자 화면 구간에 용법 상한 검증 반영"""
        drug = dict(drug, item_seq=str(item_seq), confirmed=True,
                    item_name=self.seq2name.get(str(item_seq), ""), fields={k: dict(v) for k, v in drug["fields"].items()})
        for f, x in drug["fields"].items():
            over, why = self.over_check(str(item_seq), f, x["value"])
            x["over"], x["reason"] = bool(over), why if over else ""
            if over and x["ui"] == "미리 채움":
                x["ui"] = "확인 필요(권장 용법과 다름)"
        return drug

    # ------------------------------------------------------------ 전체
    def analyze(self, img):
        t0 = time.time()
        lines, meta = self.read_lines(img)
        prompt, dropped, n_mask = build_prompt(lines)
        result, usage, llm_sec, _raw = self.call_llm(prompt)
        drugs = self.decide(lines, result)
        return dict(doc_type=(result or {}).get("doc_type", "unknown"), drugs=drugs, json_ok=result is not None,
                    privacy=dict(lines_total=len(lines), lines_dropped=len(dropped), masked=n_mask),
                    timing_sec=dict(ocr=meta["ocr_sec"], llm=round(llm_sec, 2), total=round(time.time() - t0, 2)),
                    usage=dict(input=usage.get("inputTokens"), output=usage.get("outputTokens")),
                    notice=UI_TEXT["notice"], storage=UI_TEXT["storage"],
                    version=dict(config=self.cfg["version"], prompt=self.cfg["llm"]["prompt"], rule=self.cfg["rule"]["name"]))

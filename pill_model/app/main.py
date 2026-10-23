"""
pill_model 워커 API (백엔드만 호출 — plan.md 3-2)

  GET  /health
  POST /pill/analyze · /pill/reject · /pill/imprint-choice · /pill/refine · /pill/confirm
  POST /rx/analyze   · /rx/confirm

- 식별·판정은 yakon_pill / yakon_rx 를 그대로 호출한다. 이 파일은 S3·세션·인증·동시성만 담당 (claude.md 1-5)
- 문장·버튼은 yakon_pill.MSG/BUTTONS, yakon_rx.UI_TEXT 를 그대로 돌려준다
- 처방전 사진·OCR 글자·LLM 입출력은 저장·로그하지 않는다. 로그에는 장 수·시간·약 개수·판정 종류만 (claude.md 1-7)
"""
import asyncio
import hmac
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool

from app import bg
from app.images import ImageIndex
from app.schemas import (PillAnalyzeRequest, PillConfirmRequest, PillImprintChoiceRequest, PillRefineRequest,
                         PillRejectRequest, RxAnalyzeRequest, RxConfirmRequest, camelize)
from app.sessions import SessionExpired, SessionStore
from app.settings import get_settings
from app.storage import BadKey, NotFound, Storage, TooLarge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pill_worker")


class State:
    """시작 시 한 번 만들어 요청들이 같이 쓰는 것들"""

    def __init__(self, settings, pill=None, rx=None, load_sec=None, storage=None, remover=None, images=None):
        self.settings = settings
        self.pill, self.rx, self.load_sec = pill, rx, load_sec
        self.storage = storage or Storage(settings)
        self.remover = remover or bg.BgRemover(settings.rembg_model)
        self.images = images or ImageIndex()
        self.sessions = SessionStore(settings.session_ttl_sec)
        self.sem = None  # 이벤트 루프 안에서 생성


def build_state(settings, llm_client=None):
    """운영 시작 순서 (plan.md 3-1): deploy 확인 → 공유 OCR 엔진 + 모듈 → 워밍업 → 사진 URL 색인(백그라운드)"""
    if not os.path.isdir(os.path.join(settings.deploy_dir, "cnn")) or not os.path.isdir(os.path.join(settings.deploy_dir, "rx")):
        raise RuntimeError(f"{settings.deploy_dir}/cnn·rx 가 없습니다 → scripts/fetch_models.sh 로 S3 models/ 를 받아 주세요")
    from app.ocr_engine import load_models
    pill, rx, load_sec = load_models(settings.deploy_dir, llm_client=llm_client, load_llm=settings.load_llm)
    st = State(settings, pill, rx, load_sec)
    _warmup(st)
    threading.Thread(target=st.images.load, args=(settings.data_bucket, settings.aws_region), daemon=True).start()
    return st


def _warmup(st):
    """첫 요청이 느려지지 않게 OCR·CNN 을 더미 알약 사진으로 1회 실행"""
    from PIL import Image, ImageDraw
    t = time.time()
    im = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((60, 60, 340, 240), fill=(240, 240, 235, 255))
    st.pill.prepare(im)
    log.info("warmup sec=%.1f", time.time() - t)


def create_app(state_builder=None):
    """state_builder: 테스트에서 가짜 모델·LLM 을 넣을 때 사용 (기본은 build_state)"""

    @asynccontextmanager
    async def lifespan(app):
        settings = get_settings()
        st = await run_in_threadpool(state_builder or build_state, settings)
        st.sem = asyncio.Semaphore(1)
        app.state.s = st
        log.info("ready load_sec=%s", st.load_sec)
        yield

    app = FastAPI(title="pill_model worker", lifespan=lifespan, docs_url=None, redoc_url=None)

    def st() -> State:
        return app.state.s

    def err(status, code, message):
        return HTTPException(status, detail={"code": code, "message": message})

    def auth(x_worker_token: str | None = Header(default=None)):
        expected = st().settings.worker_token
        if not expected:
            raise err(503, "not_ready", "WORKER_TOKEN 이 설정되지 않았습니다")
        if not x_worker_token or not hmac.compare_digest(x_worker_token, expected):
            raise err(401, "unauthorized", "토큰이 맞지 않습니다")

    async def exclusive(fn, *args):
        """알약·처방전 공용 동시성 1 (CPU 2코어·메모리 4GB). 60초 넘게 기다리면 busy"""
        s = st()
        try:
            await asyncio.wait_for(s.sem.acquire(), timeout=s.settings.busy_wait_sec)
        except TimeoutError:
            raise err(503, "busy", "요청이 많아 잠시 후 다시 시도해 주세요") from None
        try:
            return await run_in_threadpool(fn, *args)
        except BadKey:
            raise err(400, "bad_key", "사진 경로 형식이 맞지 않습니다") from None
        except NotFound:
            raise err(404, "not_found", "업로드된 사진을 찾을 수 없습니다") from None
        except TooLarge:
            raise err(413, "too_large", "사진은 10MB 이하만 가능합니다") from None
        except SessionExpired:
            raise err(410, "expired", "시간이 지나 처음부터 다시 진행해 주세요") from None
        finally:
            s.sem.release()

    def session(sid, kind):
        try:
            return st().sessions.get(sid, kind)
        except SessionExpired:
            raise err(410, "expired", "시간이 지나 처음부터 다시 진행해 주세요") from None

    def with_images(cands):
        imgs = st().images
        return [dict(c, image_url=imgs.url(c["item_seq"])) for c in cands or []]

    def remember(sess, cands):
        sess.setdefault("seen", {}).update({c["item_seq"]: c for c in cands})

    # ------------------------------------------------------------------ 상태
    @app.get("/health")
    def health():
        s = st()
        import cv2
        return camelize(dict(
            status="ok",
            model_loaded=dict(pill=s.pill is not None, rx=s.rx is not None, llm=bool(s.rx and s.rx.llm)),
            image_index=dict(status=s.images.status, size=len(s.images.urls), snapshot=s.images.snapshot,
                             error=s.images.error, load_sec=s.images.load_sec),
            image_index_size=len(s.images.urls),
            versions=dict(pill=s.pill.cfg.get("version") if s.pill else None, rx=s.rx.cfg.get("version") if s.rx else None,
                          rembg=s.remover.model_name),
            load_sec=s.load_sec, cv2=cv2.__version__, sessions=len(s.sessions),
        ))

    # ------------------------------------------------------------------ 알약
    def _pill_analyze(req: PillAnalyzeRequest):
        s = st()
        t0 = time.time()
        attempt = 1
        if req.prev_session_id:
            try:
                attempt = s.sessions.get(req.prev_session_id, "pill")["attempt"]
            except SessionExpired:
                pass
        keys = [req.front_key, req.back_key or req.front_key]
        opened = {}
        for k in dict.fromkeys(keys):  # 같은 사진이면 한 번만 처리
            try:
                opened[k] = bg.open_pill(s.storage.read(k, "pill"), s.remover)
            except ValueError as e:
                if str(e) == "bad_image":
                    raise err(400, "bad_image", "사진 파일을 열 수 없습니다 (jpg·png·webp)") from None
                raise
        prepared = {k: s.pill.prepare(opened[k][0]) for k in opened}
        res = s.pill.analyze(None, None, shape=req.shape, _prepared=(prepared[keys[0]], prepared[keys[1]]))
        res["candidates"] = with_images(res["candidates"])      # next_step 이 이 목록을 잘라 쓰므로 먼저 붙임
        step = s.pill.next_step(res, attempt)
        saved = []
        # 동의했고 사진 품질이 정상일 때만, 배경이 지워진 알약 조각만 저장 (처방전은 어떤 것도 저장 안 함)
        if req.save_crops and res["quality"]["ok"]:
            for side, k in zip(("front", "back"), dict.fromkeys(keys)):
                key = s.storage.save_crop(opened[k][0], side)
                if key:
                    saved.append(key)
        sid = s.sessions.create("pill", dict(prepared=(prepared[keys[0]], prepared[keys[1]]), shape=req.shape,
                                             attempt=attempt, res=dict(candidates=res["candidates"])))
        remember(s.sessions.get(sid, "pill"), res["candidates"])
        bg_sec = round(sum(v[2] for v in opened.values()), 2)
        timing = dict(res["timing_sec"], bg=bg_sec, total=round(time.time() - t0, 2))
        log.info("pill analyze step=%s band=%s bg_removed=%d sec=%.1f crops=%d", step["step"], res.get("band"),
                 sum(v[1] for v in opened.values()), timing["total"], len(saved))
        return camelize(dict(step, session_id=sid, quality=res["quality"], timing_sec=timing,
                             storage_notice=s.pill.MSG["storage"], saved_crops=len(saved),
                             version=res["version"]))

    @app.post("/pill/analyze", dependencies=[Depends(auth)])
    async def pill_analyze(req: PillAnalyzeRequest):
        return await exclusive(_pill_analyze, req)

    @app.post("/pill/reject", dependencies=[Depends(auth)])
    def pill_reject(req: PillRejectRequest):
        s = st()
        sess = session(req.session_id, "pill")
        if req.from_step == "top1":
            out = s.pill.on_reject(sess["attempt"], "top1", sess["res"])     # 1위 [아니오] → Top-3 먼저
        else:
            out = s.pill.on_reject(sess["attempt"])
            sess["attempt"] += 1                                              # 각인 입력 → 재촬영 → 종료 순서
        if "candidates" in out:
            out["candidates"] = with_images(out["candidates"])
        log.info("pill reject from=%s -> %s", req.from_step, out["step"])
        return camelize(dict(out, session_id=req.session_id))

    @app.post("/pill/imprint-choice", dependencies=[Depends(auth)])
    def pill_imprint_choice(req: PillImprintChoiceRequest):
        session(req.session_id, "pill")
        out = st().pill.on_imprint_choice(req.choice)
        # None = 글자 입력 → 프런트가 각인 입력칸을 보여주고 /pill/refine 호출
        return camelize(dict(out or dict(step="imprint_input"), session_id=req.session_id))

    def _pill_refine(req: PillRefineRequest):
        s = st()
        sess = session(req.session_id, "pill")
        out = s.pill.refine(sess["prepared"], shape=sess["shape"], imprint_front=req.imprint_front,
                            imprint_back=req.imprint_back, color=req.color)
        out["candidates"] = with_images(out["candidates"])
        sess["res"] = dict(candidates=out["candidates"])
        remember(sess, out["candidates"])
        log.info("pill refine imprint=%s color=%s", bool(req.imprint_front or req.imprint_back), bool(req.color))
        return camelize(dict(out, session_id=req.session_id))

    @app.post("/pill/refine", dependencies=[Depends(auth)])
    async def pill_refine(req: PillRefineRequest):
        return await exclusive(_pill_refine, req)

    @app.post("/pill/confirm", dependencies=[Depends(auth)])
    def pill_confirm(req: PillConfirmRequest):
        s = st()
        sess = session(req.session_id, "pill")
        cand = sess.get("seen", {}).get(req.item_seq)
        if cand is None:
            raise err(400, "bad_request", "보여준 후보 중에서 골라 주세요")
        out = s.pill.handoff(cand, req.user_question)
        return camelize(dict(out, image_url=cand.get("image_url"), session_id=req.session_id))

    # ------------------------------------------------------------------ 처방전·약봉투
    def _rx_analyze(req: RxAnalyzeRequest):
        s = st()
        if s.rx.llm is None:
            raise err(503, "not_ready", "처방전 인식(LLM)이 준비되지 않았습니다")
        data = s.storage.read(req.key, "prescription")
        from PIL import Image
        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception:
            raise err(400, "bad_image", "사진 파일을 열 수 없습니다 (jpg·png·webp)") from None
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            res = s.rx.analyze(data)
        except (ClientError, BotoCoreError) as e:
            # Bedrock 오류(AccessDenied·Throttling) — OCR 결과는 버리고 저장하지 않음 (plan.md 3-2)
            log.warning("rx llm error: %s", type(e).__name__)
            raise err(502, "llm_unavailable", "처방전 인식이 잠시 안 돼요. 잠시 후 다시 시도해 주세요") from None
        finally:
            del data
        sid = s.sessions.create("rx", dict(drugs=res["drugs"]))
        log.info("rx analyze doc=%s drugs=%d decisions=%s json_ok=%s sec=%s", res["doc_type"], len(res["drugs"]),
                 sorted({d["decision"] for d in res["drugs"]}), res["json_ok"], res["timing_sec"])
        return camelize(dict(res, session_id=sid))

    @app.post("/rx/analyze", dependencies=[Depends(auth)])
    async def rx_analyze(req: RxAnalyzeRequest):
        return await exclusive(_rx_analyze, req)

    @app.post("/rx/confirm", dependencies=[Depends(auth)])
    def rx_confirm(req: RxConfirmRequest):
        s = st()
        sess = session(req.session_id, "rx")
        if req.drug_index >= len(sess["drugs"]):
            raise err(400, "bad_request", "약 번호가 맞지 않습니다")
        if req.item_seq not in s.rx.seq2name:
            raise err(400, "bad_request", "허가 목록에 없는 품목입니다")
        drug = s.rx.confirm(sess["drugs"][req.drug_index], req.item_seq)
        sess["drugs"][req.drug_index] = drug
        log.info("rx confirm over=%s", sorted(k for k, v in drug["fields"].items() if v.get("over")))
        return camelize(dict(drug=drug, drug_index=req.drug_index, session_id=req.session_id))

    return app


app = create_app()

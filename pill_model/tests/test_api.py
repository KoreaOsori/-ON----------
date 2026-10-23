"""
API 흐름 (가짜 모델). 대화 단계 함수(next_step·on_reject·on_imprint_choice·refine·handoff)와 문장은
실제 yakon_pill 것을 그대로 상속해서 쓰고, 무거운 prepare·analyze 만 정해진 값으로 바꾼다.
"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import State, create_app
from app.pill.yakon_pill import PillIdentifier
from tests.conftest import HEADERS, put_upload

CANDS = [dict(rank=i + 1, item_seq=f"S{i}", name=f"약{i}", company="", print_front="AB", print_back="",
              shape="원형", color="하양", etc_otc="", score=0.3 - i * 0.01, rule_rank=i + 1, cnn_rank=i + 1,
              rule_score=0.5, cnn_score=0.5) for i in range(5)]


class FakePill(PillIdentifier):
    def __init__(self, band="B"):
        import numpy as np
        self.band = band
        self.cfg = dict(version="fake", rule=dict(normalize_remove=[]), ocr=dict(min_score=0.5, drop_single_hangul=True))
        self.rot = [0]
        self.COLOR = np.array(["하양", "노랑", ""])
        self.prepared_calls = 0

    def prepare(self, img, reads=None):
        self.prepared_calls += 1
        return dict(texts=["AB"], reads=[], lab=None, sims=None, t=dict(prep=0.1, ocr=0.2, cnn=0.3),
                    quality=dict(ok=True, issues=[], message=""))

    def analyze(self, front, back, shape=None, top_k=5, _prepared=None, color=None, **kw):
        A, B = _prepared
        cands = [dict(c) for c in CANDS]
        if color:
            cands = [c for c in cands if c["color"] == color][:top_k]
        return dict(query=dict(shape=shape, ocr_front=A["texts"], ocr_back=B["texts"]),
                    quality=dict(front=A["quality"], back=B["quality"], ok=True), candidates=cands[:top_k],
                    ambiguous=False, timing_sec=dict(prep=0.2, ocr=0.4, cnn=0.6, total=1.0),
                    version=dict(config="fake"), band=self.band, imprint_match=0.85)


class FakeRx:
    def __init__(self, fail=False):
        self.llm = object()
        self.fail = fail
        self.cfg = dict(version="fake")
        self.seq2name = {"R1": "가나정", "R2": "다라정"}

    def analyze(self, data):
        if self.fail:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "Converse")
        drug = dict(name_read="가나정", name_conf=0.9, decision="확인 필요", how="⑤ 오타", auto=False, item_seq=None,
                    candidates=[dict(item_seq="R1", item_name="가나정", status="")],
                    fields=dict(dose=dict(value="1정", conf=0.95, ui="미리 채움"),
                                times=dict(value=None, conf=None, ui="빈칸"),
                                days=dict(value="7", conf=0.5, ui="확인 필요")))
        return dict(doc_type="prescription", drugs=[drug], json_ok=True,
                    privacy=dict(lines_total=10, lines_dropped=3, masked=1), timing_sec=dict(ocr=1, llm=1, total=2),
                    usage=dict(input=1, output=1), notice="n", storage="s", version=dict(config="fake"))

    def confirm(self, drug, item_seq):
        return dict(drug, item_seq=item_seq, confirmed=True, item_name=self.seq2name[item_seq])


class FakeRemover:
    model_name = "fake"

    def remove(self, rgb):
        return rgb.convert("RGBA")


def make_client(pill=None, rx=None):
    def builder(settings):
        return State(settings, pill or FakePill(), rx or FakeRx(), load_sec=0, remover=FakeRemover())
    return TestClient(create_app(builder))


def pill_png():
    im = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    im.paste((250, 250, 250, 255), (10, 10, 50, 30))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_health_and_auth(env):
    with make_client() as c:
        h = c.get("/health").json()
        assert h["status"] == "ok" and h["modelLoaded"]["pill"] and h["imageIndexSize"] == 0
        key = put_upload(env, "pill", pill_png())
        assert c.post("/pill/analyze", json={"frontKey": key}).status_code == 401
        assert c.post("/pill/analyze", json={"frontKey": key}, headers={"X-Worker-Token": "x"}).status_code == 401


def test_key_rules(env):
    with make_client() as c:
        rx_key = put_upload(env, "prescription", pill_png())
        r = c.post("/pill/analyze", json={"frontKey": rx_key}, headers=HEADERS)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_key"
        missing = "pill/2026/10/23/guest/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.png"
        assert c.post("/pill/analyze", json={"frontKey": missing}, headers=HEADERS).status_code == 404
        bad = put_upload(env, "pill", b"not an image")
        r = c.post("/pill/analyze", json={"frontKey": bad}, headers=HEADERS)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_image"


def test_pill_dialog_flow(env):
    pill = FakePill(band="B")
    with make_client(pill=pill) as c:
        key = put_upload(env, "pill", pill_png())
        r = c.post("/pill/analyze", json={"frontKey": key, "shape": "원형"}, headers=HEADERS).json()
        # 한 면만 보내면 같은 사진을 두 면으로 사용하되 한 번만 처리
        assert pill.prepared_calls == 1
        assert r["step"] == "top3" and len(r["candidates"]) == 3 and r["candidates"][0]["itemSeq"] == "S0"
        assert r["message"] == PillIdentifier.MSG["top3"] and r["storageNotice"] == PillIdentifier.MSG["storage"]
        assert "imageUrl" in r["candidates"][0] and r["savedCrops"] == 0
        sid = r["sessionId"]

        r = c.post("/pill/reject", json={"sessionId": sid, "fromStep": "top3"}, headers=HEADERS).json()
        assert r["step"] == "ask_imprint" and r["buttons"] == PillIdentifier.BUTTONS["ask_imprint"]
        r = c.post("/pill/imprint-choice", json={"sessionId": sid, "choice": "각인이 없어요"}, headers=HEADERS).json()
        assert r["step"] == "ask_color" and r["buttons"] == ["노랑", "하양"]
        r = c.post("/pill/imprint-choice", json={"sessionId": sid, "choice": "AB12"}, headers=HEADERS).json()
        assert r["step"] == "imprint_input"
        r = c.post("/pill/refine", json={"sessionId": sid, "color": "하양"}, headers=HEADERS).json()
        assert r["step"] == "top3" and r["candidates"][0]["itemSeq"] == "S0"
        r = c.post("/pill/refine", json={"sessionId": sid, "imprintFront": "AB"}, headers=HEADERS).json()
        assert r["step"] == "top3"

        # 각인 입력 후에도 실패 → 재촬영 → (재촬영 사진 분석 후에도 실패) 종료
        r = c.post("/pill/reject", json={"sessionId": sid, "fromStep": "top3"}, headers=HEADERS).json()
        assert r["step"] == "retake"
        r2 = c.post("/pill/analyze", json={"frontKey": key, "prevSessionId": sid}, headers=HEADERS).json()
        r = c.post("/pill/reject", json={"sessionId": r2["sessionId"], "fromStep": "top3"}, headers=HEADERS).json()
        assert r["step"] == "give_up" and r["message"] == PillIdentifier.MSG["give_up"]

        ok = c.post("/pill/confirm", json={"sessionId": sid, "itemSeq": "S1", "userQuestion": "식후?"},
                    headers=HEADERS).json()
        assert ok["itemSeq"] == "S1" and ok["confirmedByUser"] is True and ok["userQuestion"] == "식후?"
        assert c.post("/pill/confirm", json={"sessionId": sid, "itemSeq": "NOPE"}, headers=HEADERS).status_code == 400


def test_top1_reject_goes_to_top3(env):
    with make_client(pill=FakePill(band="A")) as c:
        key = put_upload(env, "pill", pill_png())
        r = c.post("/pill/analyze", json={"frontKey": key}, headers=HEADERS).json()
        assert r["step"] == "top1" and len(r["candidates"]) == 1 and r["buttons"] == ["네", "아니오"]
        r = c.post("/pill/reject", json={"sessionId": r["sessionId"], "fromStep": "top1"}, headers=HEADERS).json()
        assert r["step"] == "top3" and [x["itemSeq"] for x in r["candidates"]] == ["S0", "S1", "S2"]


def test_crops_saved_only_with_consent(env):
    with make_client() as c:
        front, back = put_upload(env, "pill", pill_png()), put_upload(env, "pill", pill_png())
        r = c.post("/pill/analyze", json={"frontKey": front, "backKey": back}, headers=HEADERS).json()
        assert r["savedCrops"] == 0 and not (Path(env) / "crops").exists()
        r = c.post("/pill/analyze", json={"frontKey": front, "backKey": back, "saveCrops": True}, headers=HEADERS).json()
        crops = sorted(p.name for p in (Path(env) / "crops").rglob("*.png"))
        assert r["savedCrops"] == 2 and sorted(n.split("_")[1] for n in crops) == ["back.png", "front.png"]
        # 저장 경로에 사용자 ID(owner) 없음
        assert all("guest" not in str(p) for p in (Path(env) / "crops").rglob("*"))


def test_session_expired(env):
    with make_client() as c:
        r = c.post("/pill/reject", json={"sessionId": "nope", "fromStep": "top3"}, headers=HEADERS)
        assert r.status_code == 410 and r.json()["detail"]["code"] == "expired"


def test_rx_flow(env):
    with make_client() as c:
        key = put_upload(env, "prescription", pill_png(), ext="jpg")
        r = c.post("/rx/analyze", json={"key": key}, headers=HEADERS).json()
        d = r["drugs"][0]
        assert r["docType"] == "prescription" and d["nameRead"] == "가나정" and d["fields"]["times"]["value"] is None
        assert d["fields"]["times"]["ui"] == "빈칸" and r["privacy"]["linesDropped"] == 3
        r2 = c.post("/rx/confirm", json={"sessionId": r["sessionId"], "drugIndex": 0, "itemSeq": "R1"},
                    headers=HEADERS).json()
        assert r2["drug"]["confirmed"] is True and r2["drug"]["itemSeq"] == "R1"
        assert c.post("/rx/confirm", json={"sessionId": r["sessionId"], "drugIndex": 5, "itemSeq": "R1"},
                      headers=HEADERS).status_code == 400
        assert c.post("/rx/confirm", json={"sessionId": r["sessionId"], "drugIndex": 0, "itemSeq": "ZZ"},
                      headers=HEADERS).status_code == 400
        # 알약 key 로 처방전 호출 금지
        pk = put_upload(env, "pill", pill_png())
        assert c.post("/rx/analyze", json={"key": pk}, headers=HEADERS).status_code == 400


def test_rx_llm_error_is_502(env):
    with make_client(rx=FakeRx(fail=True)) as c:
        key = put_upload(env, "prescription", pill_png(), ext="jpg")
        r = c.post("/rx/analyze", json={"key": key}, headers=HEADERS)
        assert r.status_code == 502 and r.json()["detail"]["code"] == "llm_unavailable"


def test_missing_token_config_refuses(env, monkeypatch):
    monkeypatch.setenv("WORKER_TOKEN", "")
    with make_client() as c:
        key = put_upload(env, "pill", pill_png())
        assert c.post("/pill/analyze", json={"frontKey": key}, headers=HEADERS).status_code == 503


@pytest.mark.parametrize("path", ["/pill/analyze", "/rx/analyze"])
def test_validation_422(env, path):
    with make_client() as c:
        assert c.post(path, json={}, headers=HEADERS).status_code == 422

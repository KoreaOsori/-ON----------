"""pill_model 워커 연동 (알약 /pill/*, 처방전 OCR_PROVIDER=worker). 워커는 가짜 HTTP 응답으로 대신한다."""

import httpx
import pytest

from app.core.config import settings
from app.modules.ocr import service as ocr_service
from app.modules.pill import service

GUEST_KEY = "pill/2026/10/23/guest/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.png"
RX_KEY = "prescription/2026/10/23/guest/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.jpg"


@pytest.fixture
def worker(monkeypatch):
    """service.call 이 보내는 요청을 기록하고 정해 둔 응답을 돌려주는 가짜 워커"""
    calls = []
    responses = {}

    def handler(request: httpx.Request):
        calls.append(request)
        status, body = responses.get(request.url.path, (200, {}))
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(settings, "pill_worker_url", "http://worker.test:8000")
    monkeypatch.setattr(settings, "pill_worker_token", "t0k")
    return calls, responses


async def test_pill_analyze_forwards_camel_case_with_token(client, worker):
    calls, responses = worker
    responses["/pill/analyze"] = (200, {"step": "top1", "sessionId": "s1", "candidates": [{"itemSeq": "1"}]})
    r = await client.post("/api/v1/pill/analyze", json={"frontKey": GUEST_KEY, "saveCrops": True})
    assert r.status_code == 200 and r.json()["step"] == "top1"
    sent = calls[0]
    assert sent.headers["x-worker-token"] == "t0k"
    body = httpx.Response(200, content=sent.content).json()
    assert body["frontKey"] == GUEST_KEY and body["saveCrops"] is True and body["backKey"] is None


async def test_pill_analyze_rejects_other_owner(client, worker):
    other = GUEST_KEY.replace("/guest/", "/7f1c2d3e-aaaa-bbbb-cccc-123456789012/")
    r = await client.post("/api/v1/pill/analyze", json={"frontKey": GUEST_KEY, "backKey": other})
    assert r.status_code == 403
    assert worker[0] == []


async def test_worker_errors_are_mapped(client, worker):
    _, responses = worker
    responses["/pill/reject"] = (
        410,
        {"detail": {"code": "expired", "message": "시간이 지나 처음부터 다시 진행해 주세요"}},
    )
    r = await client.post("/api/v1/pill/reject", json={"sessionId": "x", "fromStep": "top3"})
    assert r.status_code == 410 and r.json()["detail"]["code"] == "expired"
    # 토큰 불일치(401)는 서버 설정 문제 → 프런트에는 502
    responses["/pill/refine"] = (401, {"detail": {"code": "unauthorized", "message": "x"}})
    r = await client.post("/api/v1/pill/refine", json={"sessionId": "x", "color": "하양"})
    assert r.status_code == 502


async def test_worker_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "pill_worker_url", None)
    r = await client.post("/api/v1/pill/analyze", json={"frontKey": GUEST_KEY})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "not_configured"


async def test_prescription_via_worker_keeps_old_fields(client, worker, monkeypatch):
    monkeypatch.setattr(settings, "ocr_provider", "worker")
    _, responses = worker
    drug = {
        "nameRead": "가나정",
        "itemName": "가나정10밀리그램",
        "decision": "자동 배치",
        "candidates": [],
        "fields": {
            "dose": {"value": "1정", "conf": 0.98, "ui": "미리 채움"},
            "times": {"value": "3", "conf": 0.7, "ui": "확인 필요"},
            "days": {"value": None, "conf": None, "ui": "빈칸"},
        },
    }
    responses["/rx/analyze"] = (
        200,
        {
            "sessionId": "s",
            "docType": "prescription",
            "drugs": [drug],
            "notice": "n",
            "storage": "st",
            "jsonOk": True,
            "privacy": {"linesTotal": 3},
        },
    )
    r = await client.post("/api/v1/ocr/prescriptions", json={"objectKey": RX_KEY})
    body = r.json()
    assert r.status_code == 200 and body["provider"] == "worker" and body["sessionId"] == "s"
    # 확신도 높은 값만 숫자로, 나머지는 null
    assert body["candidates"] == [
        {"name": "가나정10밀리그램", "amount": 1, "timesPerDay": None, "days": None}
    ]
    assert body["drugs"][0]["fields"]["days"]["ui"] == "빈칸"


async def test_prescription_owner_check(client):
    other = RX_KEY.replace("/guest/", "/7f1c2d3e-aaaa-bbbb-cccc-123456789012/")
    r = await client.post("/api/v1/ocr/prescriptions", json={"objectKey": other})
    assert r.status_code == 403


def test_confident_int():
    assert ocr_service._confident_int({"value": "1정", "ui": "미리 채움"}) == 1
    assert ocr_service._confident_int({"value": "0.5정", "ui": "미리 채움"}) is None
    assert ocr_service._confident_int({"value": "3", "ui": "확인 필요"}) is None
    assert service.owner_of(GUEST_KEY) == "guest" and service.owner_of("bad") == ""

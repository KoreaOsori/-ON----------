"""
통합: 실제 모델(deploy/) + fixture 사진으로 워커 API 를 끝까지 호출해 Colab 결과와 같은지 확인.

- 알약: /pill/analyze 의 step·band·imprintMatch·1위, top1 이면 [아니오] → Top-3 가 fixture top3 와 같은지
- 처방전: LLM 대신 fixture 의 llm_result 를 돌려주는 가짜 Bedrock 클라이언트 → /rx/analyze 의 drugs == fixture drugs
  (claude.md 3: LLM 을 다시 호출한 결과로 비교하지 않음). 처방전 글자는 출력하지 않는다.
deploy/ 나 fixture 사진이 없으면 건너뜀. 실행: python -m pytest -q tests/test_models.py (약 2~3분)
"""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import build_state, create_app
from app.schemas import camelize
from tests.conftest import HEADERS, put_upload

FX = Path(os.environ.get("FIXTURES_DIR", Path(__file__).parent / "fixtures"))
DEPLOY = os.environ.get("DEPLOY_DIR", "deploy")
PILL = sorted((FX / "pill").glob("*.expected.json"))
RX = sorted((FX / "rx").glob("*.expected.json"))

pytestmark = pytest.mark.skipif(not (Path(DEPLOY, "cnn").is_dir() and PILL and RX), reason="deploy/ 또는 fixture 없음")


class ReplayLLM:
    """Bedrock Converse 와 같은 모양으로 미리 넣어 둔 llm_result 를 돌려줌"""

    def __init__(self):
        self.next = None
        self.calls = 0

    def converse(self, **kw):
        self.calls += 1
        return {"output": {"message": {"content": [{"text": json.dumps(self.next, ensure_ascii=False)}]}},
                "usage": {"inputTokens": 0, "outputTokens": 0}}


@pytest.fixture(scope="module")
def client_llm(tmp_path_factory):
    up = tmp_path_factory.mktemp("uploads")
    mp = pytest.MonkeyPatch()
    for k, v in dict(WORKER_TOKEN=HEADERS["X-Worker-Token"], LOCAL_UPLOAD_DIR=str(up), DATA_BUCKET="",
                     LOAD_LLM="false", DEPLOY_DIR=DEPLOY).items():
        mp.setenv(k, v)
    llm = ReplayLLM()
    with TestClient(create_app(lambda s: build_state(s, llm_client=llm))) as c:
        yield c, llm, up
    mp.undo()


def norm(x):
    return json.loads(json.dumps(x, ensure_ascii=False))


@pytest.mark.parametrize("jf", PILL, ids=[p.stem for p in PILL])
def test_pill_api_matches_colab(client_llm, jf):
    c, _, up = client_llm
    fx = json.loads(jf.read_text(encoding="utf-8"))
    keys = [put_upload(up, "pill", (FX / "pill" / fx["code"] / p["file"]).read_bytes()) for p in fx["photos"]]
    r = c.post("/pill/analyze", json={"frontKey": keys[0], "backKey": keys[1], "shape": fx.get("shape")}, headers=HEADERS)
    assert r.status_code == 200, r.text
    r = r.json()
    exp = fx["expected"]
    assert r["step"] == exp["next_step"]
    assert r["band"] == exp["band"] and r["imprintMatch"] == exp["imprint_match"]
    assert r["candidates"][0]["itemSeq"] == exp["top3"][0]
    if r["step"] == "top1":
        r = c.post("/pill/reject", json={"sessionId": r["sessionId"], "fromStep": "top1"}, headers=HEADERS).json()
    assert [x["itemSeq"] for x in r["candidates"]] == exp["top3"]


@pytest.mark.parametrize("jf", RX, ids=[f"rx{i}" for i in range(len(RX))])
def test_rx_api_matches_colab(client_llm, jf):
    c, llm, up = client_llm
    fx = json.loads(jf.read_text(encoding="utf-8"))
    llm.next = fx["llm_result"]
    key = put_upload(up, "prescription", (FX / "rx" / fx["image"]).read_bytes(), ext="jpg")
    r = c.post("/rx/analyze", json={"key": key}, headers=HEADERS)
    assert r.status_code == 200, r.status_code
    got = r.json()
    # 글자를 출력하지 않도록 비교 결과만 assert (실패 메시지에 내용이 찍히지 않게 bool 로)
    same = norm(got["drugs"]) == norm(camelize(fx["drugs"]))
    assert same, f"drugs differ: n={len(got['drugs'])} vs {len(fx['drugs'])}"
    assert got["privacy"]["linesTotal"] == fx["n_lines"]

"""
PaddleOCR 엔진 1개를 만들어 알약(yakon_pill)·처방전(yakon_rx)이 같이 쓴다 (plan.md 0-5).

- 엔진은 yakon_pill 의 _make_ocr() 를 그대로 호출해서 만든다.
  → Colab 에서 검증한 생성 인자(검출 640, rec batch 16 등)와 글자 하나 다르지 않게 하기 위해 (인자를 여기서 다시 쓰지 않음)
- 처방전은 같은 엔진에서 호출할 때만 검출 1280 을 넘긴다 (config_rx.json per_call_limit=true, Colab R-E3 ② 실측 동일)
- 모델 파일은 PADDLE_PDX_CACHE_HOME/official_models/ 에 연결된 deploy/ocr_models/… 에서 읽는다 (인터넷 다운로드 없음)
"""
import os
import time

from app.pill.yakon_pill import PillIdentifier
from app.rx.yakon_rx import RxReader


def load_models(deploy_dir="deploy", llm_client=None, load_llm=True):
    """알약·처방전 모듈과 공유 OCR 엔진을 만든다 → (PillIdentifier, RxReader, 걸린 시간)

    llm_client: 테스트에서 LLM 없이 돌릴 때 load_llm=False (fixture 의 llm_result 로 decide() 만 확인)
    """
    t = time.time()
    # 1) 알약 모듈을 OCR 없이 먼저 만든다 (CNN·DB만 적재)
    pill = PillIdentifier(os.path.join(deploy_dir, "cnn"), load_ocr=False)
    # 2) 검증된 모듈 자신의 생성 함수로 엔진 1개 생성 → 알약에 넣기
    engine = pill._make_ocr()
    pill.ocr = engine
    # 3) 처방전 모듈에 같은 엔진을 넘긴다 (yakon_rx 가 ocr= 인자를 지원)
    rx = RxReader(os.path.join(deploy_dir, "rx"), ocr=engine, llm_client=llm_client, load_llm=load_llm)
    return pill, rx, round(time.time() - t, 1)

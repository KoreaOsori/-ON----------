"""
알약 사진 배경 제거 (rembg). 모델 이름은 환경변수 REMBG_MODEL (plan.md 3-4 실험 후 확정, bria-rmbg 금지).

yakon_pill 은 알파 채널로 알약 영역을 찾는다. 이미 배경이 지워진 사진(알파 있음)은 그대로 쓰고,
알파가 없는 일반 사진만 rembg 로 지운다 — 판단 기준은 yakon_pill._rgba 와 같음 (투명 픽셀 1% 미만 → 배경 있음).
"""
import io
import threading
import time

import numpy as np

# 휴대폰 원본(4000px 이상)을 그대로 넣으면 메모리·시간만 늘어남 → 긴 변을 줄인 뒤 배경 제거
# (rembg 모델 입력은 320~1024px 라 결과 마스크 품질에는 영향이 작음 — 추론, 3-4 실험에서 확인)
MAX_SIDE = 2048

BANNED = {"bria-rmbg"}  # 상업 이용 유료 (claude.md 2)


class BgRemover:
    def __init__(self, model_name="u2netp"):
        if model_name in BANNED:
            raise ValueError(f"{model_name} 사용 금지 (상업 이용 유료)")
        self.model_name = model_name
        self._session = None
        self._lock = threading.Lock()

    def _get(self):
        with self._lock:
            if self._session is None:
                from rembg import new_session
                self._session = new_session(self.model_name)
            return self._session

    def remove(self, rgb):
        from rembg import remove
        return remove(rgb, session=self._get()).convert("RGBA")


def has_alpha(im):
    if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
        return False
    a = np.array(im.convert("RGBA"))[:, :, 3]
    return (a < 250).mean() >= 0.01


def open_pill(data, remover):
    """사진 bytes → (RGBA 이미지, 배경 제거 여부, 걸린 초)"""
    from PIL import Image, ImageOps
    t = time.time()
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # 손상·지원하지 않는 형식
        raise ValueError("bad_image") from e
    im = ImageOps.exif_transpose(im)
    if has_alpha(im):
        return im.convert("RGBA"), False, round(time.time() - t, 2)
    im = im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.BICUBIC)
    return remover.remove(im), True, round(time.time() - t, 2)

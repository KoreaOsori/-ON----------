"""작은 부품: camelize · 세션 TTL · key 검사 · image_url 결합 · 알파 판단"""
import io
import time

import pytest
from PIL import Image

from app.bg import BgRemover, has_alpha, open_pill
from app.images import pick_urls
from app.schemas import PillAnalyzeRequest, camelize
from app.sessions import SessionExpired, SessionStore
from app.storage import BadKey, Storage


def test_camelize_nested_keys_only():
    src = {"timing_sec": {"ocr_front": 1}, "candidates": [{"item_seq": "1", "image_url": None}], "fields": {"dose": 1}}
    assert camelize(src) == {"timingSec": {"ocrFront": 1}, "candidates": [{"itemSeq": "1", "imageUrl": None}],
                             "fields": {"dose": 1}}
    # 값(문장·한글)은 바꾸지 않음
    assert camelize({"ui": "확인 필요(범위 밖)"}) == {"ui": "확인 필요(범위 밖)"}


def test_request_accepts_camel_case():
    r = PillAnalyzeRequest.model_validate({"frontKey": "a", "saveCrops": True})
    assert (r.front_key, r.back_key, r.save_crops) == ("a", None, True)


def test_session_ttl_and_kind():
    s = SessionStore(ttl_sec=600)
    sid = s.create("pill", {"attempt": 1})
    assert s.get(sid, "pill")["attempt"] == 1
    with pytest.raises(SessionExpired):
        s.get(sid, "rx")            # 다른 종류 세션으로는 못 씀
    short = SessionStore(ttl_sec=0)
    sid2 = short.create("rx", {})
    time.sleep(0.01)
    with pytest.raises(SessionExpired):
        short.get(sid2, "rx")


@pytest.mark.parametrize("key,purpose,ok", [
    ("pill/2026/10/23/guest/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.png", "pill", True),
    ("prescription/2026/10/23/7f1c2d3e-aaaa-bbbb-cccc-123456789012/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.jpg",
     "prescription", True),
    ("prescription/2026/10/23/guest/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.jpg", "pill", False),   # 경로 종류 불일치
    ("pill/2026/10/23/guest/../../x.png", "pill", False),
    ("crops/2026/10/23/guest/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.png", "pill", False),
    ("pill/2026/10/23/guest/0b6c1f0e-8d1d-4f7a-9a51-3f5d1f0b2c11.gif", "pill", False),
])
def test_key_check(key, purpose, ok):
    if ok:
        Storage.check_key(key, purpose)
    else:
        with pytest.raises(BadKey):
            Storage.check_key(key, purpose)


def test_pick_urls_first_by_image_id_and_skip_empty():
    seqs = ["A", "B", "C", None]
    pills = [
        [{"image_id": "2", "item_image": "u2"}, {"image_id": "1", "item_image": "u1"}],
        [{"image_id": "1", "item_image": ""}],
        None,
        [{"image_id": "1", "item_image": "x"}],
    ]
    assert pick_urls(seqs, pills) == {"A": "u1"}


def test_read_urls_with_snapshot_partition_path(tmp_path):
    """EC2 10-23 ArrowTypeError 재현: 경로 snapshot=… + 파일 안 snapshot 컬럼(string) 이 함께 있어도 읽혀야 함"""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.images import read_urls
    d = tmp_path / "silver" / "drug_product" / "snapshot=2026-10-23"
    d.mkdir(parents=True)
    pq.write_table(pa.table({
        "item_seq": ["A", "B"],
        "pills": [[{"image_id": "2", "item_image": "u2"}, {"image_id": "1", "item_image": "u1"}], None],
        "snapshot": ["2026-10-23", "2026-10-23"],
    }), d / "data.parquet")
    assert read_urls(str(d / "data.parquet")) == {"A": "u1"}


def _png(mode, color):
    buf = io.BytesIO()
    Image.new(mode, (50, 40), color).save(buf, format="PNG")
    return buf.getvalue()


def test_has_alpha_follows_yakon_rule():
    assert not has_alpha(Image.new("RGB", (10, 10)))
    assert not has_alpha(Image.new("RGBA", (10, 10), (1, 2, 3, 255)))      # 알파 채널만 있고 전부 불투명
    im = Image.new("RGBA", (10, 10), (1, 2, 3, 255))
    im.putpixel((0, 0), (0, 0, 0, 0))
    assert has_alpha(im)                                                   # 투명 1% 이상


class _Remover:
    model_name = "fake"

    def __init__(self):
        self.calls = 0

    def remove(self, rgb):
        self.calls += 1
        return rgb.convert("RGBA")


def test_open_pill_removes_bg_only_without_alpha():
    r = _Remover()
    im, removed, _ = open_pill(_png("RGB", (200, 10, 10)), r)
    assert removed and r.calls == 1 and im.mode == "RGBA"
    im, removed, _ = open_pill(_png("RGBA", (0, 0, 0, 0)), r)
    assert not removed and r.calls == 1
    with pytest.raises(ValueError):
        open_pill(b"not an image", r)


def test_bria_banned():
    with pytest.raises(ValueError):
        BgRemover("bria-rmbg")

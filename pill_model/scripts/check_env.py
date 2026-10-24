"""
빌드 마지막 검사 (plan.md 3-3). 하나라도 틀리면 종료 코드 1 → docker build 실패.
Colab 검증 환경과 버전이 다르면 OCR 결과(지문)가 달라질 수 있어서, 이미지 단계에서 미리 막는다.
"""
import sys
from importlib import metadata

# constraints.txt 와 같은 값 — 여기서 한 번 더 확인 (pip 가 조용히 다른 버전을 깐 경우를 잡기 위해)
EXPECT = {
    "numpy": "2.1.3",
    "pillow": "11.3.0",
    "pandas": "2.2.3",
    "scipy": "1.16.3",
    "paddlepaddle": "3.2.2",
    "paddleocr": "3.7.0",
    "paddlex": "3.7.2",
    "opencv-contrib-python": "4.10.0.84",
    "rapidfuzz": "3.14.6",
    "timm": "1.0.30",
    "rembg": "2.0.69",
}
errors = []

for name, want in EXPECT.items():
    try:
        got = metadata.version(name)
    except metadata.PackageNotFoundError:
        got = None
    ok = got == want
    print(f"{'OK ' if ok else 'ERR'} {name:24s} {got} (기대 {want})")
    if not ok:
        errors.append(name)

torch_ver = metadata.version("torch")
print(f"{'OK ' if torch_ver.startswith('2.11.0') else 'ERR'} {'torch':24s} {torch_ver}")
if not torch_ver.startswith("2.11.0"):
    errors.append("torch")

# cv2 를 제공하는 opencv 패키지는 정확히 1개여야 한다 (여러 개면 마지막에 깔린 것이 cv2/ 를 덮어씀)
opencv = sorted(d.metadata["Name"] for d in metadata.distributions() if d.metadata["Name"].lower().startswith("opencv"))
print(f"{'OK ' if opencv == ['opencv-contrib-python'] else 'ERR'} opencv 패키지 목록       {opencv}")
if opencv != ["opencv-contrib-python"]:
    errors.append("opencv 패키지가 1개가 아님")

import cv2  # noqa: E402

print(f"{'OK ' if cv2.__version__ == '4.10.0' else 'ERR'} {'cv2.__version__':24s} {cv2.__version__}")
if cv2.__version__ != "4.10.0":
    errors.append("cv2")

# 배경 제거 1회 실행 (모델은 빌드 때 받아 둔 U2NET_HOME 에서 읽음 — 인터넷 없이 동작해야 함)
try:
    import numpy as np
    from PIL import Image
    from rembg import new_session, remove

    img = Image.fromarray(np.full((64, 64, 3), 200, dtype=np.uint8))
    out = remove(img, session=new_session("u2netp"))
    print(f"OK  rembg 1회 실행            mode={out.mode} size={out.size}")
except Exception as e:  # 원인 그대로 출력
    print(f"ERR rembg 1회 실행            {type(e).__name__}: {e}")
    errors.append("rembg")

if errors:
    print("실패:", ", ".join(errors))
    sys.exit(1)
print("환경 검사 통과")

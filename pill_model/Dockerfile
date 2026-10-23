# pill_model 워커 이미지 (알약 /pill/* + 처방전 /rx/*)
# 버전 근거: plan.md 0-3 (Colab CPU 실측), 설치 방식: plan.md 3-3
# 모델·데이터(deploy/)는 이미지에 넣지 않고 compose 에서 읽기 전용으로 연결한다.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # rembg 모델 가중치 위치 (빌드 때 받아 둠 → 실행 중 다운로드 없음)
    U2NET_HOME=/opt/rembg \
    # PaddleX 캐시 위치. official_models/ 에 deploy/ocr_models/… 를 연결한다 (compose.yaml)
    PADDLE_PDX_CACHE_HOME=/home/app/.paddlex \
    # 모델 원본 연결 확인 생략 (로그의 안내 옵션). 인터넷 다운로드 없이 캐시만 사용
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    # Colab 에서 겪은 HF 401 방지
    HF_HUB_DISABLE_IMPLICIT_TOKEN=1

# opencv-contrib-python 은 headless 가 아니라 libGL·glib 가 필요, paddle 은 OpenMP(libgomp)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY constraints.txt requirements.txt ./

# 1) torch CPU 빌드 먼저 (PyPI 의 torch 는 CUDA 포함이라 수 GB) — 이후 timm 이 torch 를 다시 받지 않게 함
RUN pip install -c constraints.txt --index-url https://download.pytorch.org/whl/cpu \
        torch==2.11.0+cpu torchvision==0.26.0+cpu

# 2) 나머지 (paddle·OCR·CNN·API). 모든 설치에 constraints 를 건다
RUN pip install -c constraints.txt -r requirements.txt

# 3) rembg: 2.0.69 를 의존성 없이 설치하고, 실제로 쓰는 의존성만 따로 설치
#    (rembg 가 요구하는 opencv-python-headless 를 깔면 cv2 가 2개가 됨 — plan.md 3-3)
RUN pip install -c constraints.txt --no-deps rembg==2.0.69 \
 && pip install -c constraints.txt onnxruntime pymatting scikit-image pooch jsonschema tqdm

# 4) 배경 제거 후보 모델 가중치를 미리 받아 둠 (3-4 실험 후보. bria-rmbg 는 금지)
RUN python -c "from rembg import new_session; [new_session(m) for m in ('u2netp', 'isnet-general-use', 'silueta')]" \
 && ls -la /opt/rembg

# 5) 빌드 마지막 검사: cv2 4.10.0·opencv 패키지 1개·numpy/pillow 버전·rembg 1회 실행. 실패하면 빌드 중단
COPY scripts/check_env.py /tmp/check_env.py
RUN python /tmp/check_env.py && pip freeze > /app/requirements.lock.txt

# 비루트 사용자로 실행
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /home/app/.paddlex/official_models \
 && chown -R app:app /home/app /opt/rembg
COPY --chown=app:app app/ /app/app/
COPY --chown=app:app scripts/ /app/scripts/
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

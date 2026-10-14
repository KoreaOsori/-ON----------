FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home pipeline
COPY --chown=pipeline:pipeline . .
USER pipeline
ENTRYPOINT ["python", "run.py"]
CMD ["--help"]

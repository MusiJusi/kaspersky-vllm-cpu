# syntax=docker/dockerfile:1
FROM python:3.12.12-slim-bookworm@sha256:2986c55feb36e6cae00fa1fefb454283e4b33f35e75ff8bdd123b134130be301

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    HOME=/tmp/home HF_HOME=/tmp/huggingface HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 HF_HUB_DISABLE_XET=1
COPY downloader/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /app/requirements.txt \
    && python -m pip check \
    && groupadd --gid 10001 inference \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp/home inference \
    && mkdir -p /models /tmp/home \
    && chown 10001:10001 /models /tmp/home
COPY src/app/__init__.py src/app/model_store.py src/app/download_model.py /app/app/
USER 10001:10001
WORKDIR /app
ENTRYPOINT ["python", "-m", "app.download_model"]

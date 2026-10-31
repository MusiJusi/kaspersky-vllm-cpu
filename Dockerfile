# syntax=docker/dockerfile:1
FROM python:3.12.12-slim-bookworm@sha256:2986c55feb36e6cae00fa1fefb454283e4b33f35e75ff8bdd123b134130be301

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOME=/tmp/home \
    HF_HOME=/tmp/huggingface \
    VLLM_TARGET_DEVICE=cpu \
    VLLM_NO_USAGE_STATS=1 \
    VLLM_LOGGING_CONFIG_PATH=/app/config/logging.json

RUN apt-get update \
    && apt-get install -y --no-install-recommends libnuma1 libgomp1 libtcmalloc-minimal4 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    LD_PRELOAD= python -m pip install --no-cache-dir --no-deps uv==0.13.6 \
    && LD_PRELOAD= uv pip install --system --require-hashes --torch-backend cpu -r /app/requirements.txt \
    && LD_PRELOAD= python -m pip check

RUN groupadd --gid 10001 inference \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp/home inference \
    && mkdir -p /models /config /tmp/home \
    && chown 10001:10001 /models /tmp/home

ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libtcmalloc_minimal.so.4:/usr/local/lib/libiomp5.so

COPY src/ /app/
COPY config/ /app/config/
USER 10001:10001
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["python", "-m", "app.launch"]

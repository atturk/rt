# syntax=docker/dockerfile:1
# RT in un container (RT4-G1). Su Mac il default resta nativo (launchd, 'rt service'): qui
# macparakeet non gira, quindi il worker del container non trascrive audio (i job di
# trascrizione aspettano un worker sul Mac o un motore STT "custom"). Vedi docs/SELF_HOSTING.md.

# 1. Web app (SPA): compilata qui, nell'immagine finale non serve Node
FROM node:22-bookworm-slim AS spa
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. Runtime Python
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RT_DATA_DIR=/data \
    PATH=/opt/rt/bin:$PATH \
    PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg chromium \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/rt
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt "psycopg[binary]>=3.2"
COPY VERSION ./
COPY bin/ bin/
COPY config.example/ config.example/
COPY rt/ rt/
COPY docker/entrypoint.sh docker/entrypoint.sh
COPY --from=spa /src/frontend/dist/ rt/spa/
RUN useradd --create-home --uid 1000 rt \
    && mkdir -p /data \
    && chown rt:rt /data \
    && chmod +x bin/rt docker/entrypoint.sh
USER rt
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health', timeout=2)" || exit 1
ENTRYPOINT ["/opt/rt/docker/entrypoint.sh"]
CMD ["api", "--host", "0.0.0.0", "--service"]

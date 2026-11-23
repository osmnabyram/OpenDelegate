# Vekil — Render Docker imajı (python 3.12 + sabit sürüm rclone)

# ---- rclone: sabit sürüm, SHA256 doğrulamalı ----
FROM debian:bookworm-slim AS rclone
ARG RCLONE_VERSION=v1.76.0
ARG RCLONE_SHA256=b00f00b3266c3764413afe599d3ec316f6f43b3e0ea8a0bc1d186d2133e46df7
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && curl -fsSL -o /tmp/rclone.zip "https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-linux-amd64.zip" \
 && echo "${RCLONE_SHA256}  /tmp/rclone.zip" | sha256sum -c - \
 && unzip -q /tmp/rclone.zip -d /tmp \
 && install -m 0755 "/tmp/rclone-${RCLONE_VERSION}-linux-amd64/rclone" /usr/local/bin/rclone

# ---- uygulama ----
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RCLONE_CONFIG=/etc/secrets/rclone.conf

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Render $PORT'u kendisi verir (varsayılan 10000)
EXPOSE 10000
CMD ["python", "vekil/main.py"]

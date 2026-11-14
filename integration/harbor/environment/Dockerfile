FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY bench_daemon_start.c /tmp/bench_daemon_start.c
RUN gcc -std=gnu11 -O2 -Wall -Wextra /tmp/bench_daemon_start.c -o /usr/local/bin/bench-daemon-start

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates bash coreutils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g opencode-ai@1.19.5 \
    && npm cache clean --force \
    && mv /usr/local/bin/opencode /usr/local/bin/opencode-bin \
    && printf '#!/bin/sh\nexport GOOGLE_GENERATIVE_AI_API_KEY="${GOOGLE_GENERATIVE_AI_API_KEY:-${GEMINI_API_KEY:-}}"\nexec /usr/local/bin/opencode-bin "$@"\n' > /usr/local/bin/opencode \
    && chmod 0755 /usr/local/bin/opencode

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt \
    && printf '/srv/bench_daemon/src\n' > /usr/local/lib/python3.12/site-packages/bench_daemon.pth \
    && chmod 0644 /usr/local/lib/python3.12/site-packages/bench_daemon.pth

RUN useradd -m -u 1000 -s /bin/bash agent \
    && mkdir -p /srv/bench_daemon /run/bench /app /logs/artifacts /logs/agent

COPY --from=builder /usr/local/bin/bench-daemon-start /usr/local/bin/bench-daemon-start
COPY daemon/ /srv/bench_daemon/
COPY public/ /app/

RUN chown -R root:root /srv/bench_daemon \
    && chmod -R 0700 /srv/bench_daemon \
    && chown root:root /usr/local/bin/bench-daemon-start \
    && chmod 04755 /usr/local/bin/bench-daemon-start \
    && chown root:root /logs /logs/artifacts /run/bench \
    && chmod 0755 /logs /logs/artifacts /run/bench \
    && chown -R agent:agent /home/agent /app /logs/agent

ENV HOME=/home/agent PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER agent

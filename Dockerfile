# MidiMCP: retro MIDI composer — MCP server + renderer (web UI arrives in later features).
# Ubuntu 24.04 base: FluidSynth 2.3.4 + FluidR3 GM, the exact versions the render
# determinism tests and docs/reference/08-soundbanks.md checksum were verified against.
FROM ubuntu:24.04

LABEL org.opencontainers.image.source="https://github.com/bgoldbeck/MidiMCP" \
      org.opencontainers.image.description="MidiMCP retro MIDI composer (MCP server + FluidSynth renderer)" \
      org.opencontainers.image.licenses="Proprietary"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH \
    MIDIMCP_DATA_DIR=/data \
    MIDIMCP_HOST=0.0.0.0 \
    MIDIMCP_PORT=8765

# apt-get update is retried: Ubuntu mirrors briefly serve mismatched indexes while syncing.
RUN for attempt in 1 2 3 4 5; do \
      apt-get -o Acquire::Retries=3 update && break; \
      echo "apt-get update failed (attempt $attempt/5), retrying in 30s..." >&2; \
      rm -rf /var/lib/apt/lists/*; sleep 30; \
    done \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
      python3 python3-venv fluidsynth fluid-soundfont-gm lame tini \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && rm -rf /app/src

# Run as the TrueNAS "apps" user by default (UID/GID 568); override with `user:` in compose.
RUN groupadd --system --gid 568 apps \
 && useradd --system --uid 568 --gid 568 --home-dir /data --shell /usr/sbin/nologin apps \
 && mkdir -p /data && chown 568:568 /data
USER 568:568
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"MIDIMCP_PORT\",\"8765\")}/healthz', timeout=4)"

ENTRYPOINT ["tini", "--"]
CMD ["midimcp", "serve"]

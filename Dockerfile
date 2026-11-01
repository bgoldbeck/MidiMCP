# MidiMCP: retro MIDI composer — MCP server, web UI and FluidSynth renderer.
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

# Layers are ordered from "almost never changes" to "changes every commit". Docker only
# rebuilds (and the publish only uploads) the first layer that changed and those after it,
# so the big soundfont and system packages are uploaded once and then reused for years.
# Add new system tools to the "extra tools" layer, never to the layers above it.
COPY docker/apt-install.sh /usr/local/bin/apt-install.sh

# 1. General MIDI soundfont (~140 MB, the largest layer).
RUN sh /usr/local/bin/apt-install.sh fluid-soundfont-gm

# 2. Runtime: Python, FluidSynth, tini.
RUN sh /usr/local/bin/apt-install.sh python3 python3-venv fluidsynth tini \
 && python3 -m venv /opt/venv

# 3. Extra tools (small). New packages go here: changing this line re-uploads only this layer.
RUN sh /usr/local/bin/apt-install.sh lame

# Run as the TrueNAS "apps" user by default (UID/GID 568); override with `user:` in compose.
RUN groupadd --system --gid 568 apps \
 && useradd --system --uid 568 --gid 568 --home-dir /data --shell /usr/sbin/nologin apps \
 && mkdir -p /data && chown 568:568 /data

# 4. Python dependencies: rebuilt only when pyproject.toml changes.
WORKDIR /app
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
      > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# 5. MidiMCP itself (small): the only layer a normal code change uploads.
# The source is bind-mounted (not copied), so it does not add a second layer; pip
# builds in /tmp/build because the mount is discarded after this step.
RUN --mount=type=bind,target=/tmp/src \
    mkdir /tmp/build \
 && cp -r /tmp/src/pyproject.toml /tmp/src/README.md /tmp/src/src /tmp/build/ \
 && pip install --no-deps /tmp/build \
 && rm -rf /tmp/build

USER 568:568
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"MIDIMCP_PORT\",\"8765\")}/healthz', timeout=4)"

ENTRYPOINT ["tini", "--"]
CMD ["midimcp", "serve"]

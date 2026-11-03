# Bootstrap verified HTTPS before apt installs Ubuntu's maintained CA package.
# Mozilla CA bundle (MPL-2.0), immutable dated release from curl's CA extract.
FROM ubuntu:24.04 AS ubuntu-https
ADD --checksum=sha256:796f1389bfea13c0ed78f663b765baaff54a508e5483786bd6ece73c5e3e3cbe \
    https://curl.se/ca/cacert-2026-10-20.pem /etc/ssl/certs/ca-certificates.crt
RUN chmod 0755 /etc/ssl /etc/ssl/certs \
 && chmod 0644 /etc/ssl/certs/ca-certificates.crt \
 && sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources

# sfizz sources and all Git-linked dependencies are pinned by commit; only build
# stages access the network. No plugin host or runtime sample downloader is used.
FROM ubuntu-https AS sfizz-build
COPY docker/apt-install.sh /usr/local/bin/apt-install.sh
RUN sh /usr/local/bin/apt-install.sh git ca-certificates cmake make g++ pkg-config
WORKDIR /build/sfizz
RUN git init \
 && git remote add origin https://github.com/sfztools/sfizz.git \
 && git fetch --depth 1 origin 4e70dc0bef53b41f2853ed46e26f5911114c92d0 \
 && git checkout --detach FETCH_HEAD \
 && test "$(git rev-parse HEAD)" = 4e70dc0bef53b41f2853ed46e26f5911114c92d0 \
 && git submodule update --init --recursive --depth 1
RUN cmake -S . -B /build/out -DCMAKE_BUILD_TYPE=Release \
      -DSFIZZ_JACK=OFF -DSFIZZ_RENDER=ON -DSFIZZ_SHARED=OFF \
      -DSFIZZ_TESTS=OFF -DENABLE_LTO=OFF \
 && cmake --build /build/out --target sfizz_render --parallel 2 \
 && mkdir -p /notices \
 && find . -type f \( -iname '*license*' -o -iname '*copying*' -o -name AUTHORS.md \) \
      -not -path './.git/*' -exec cp --parents '{}' /notices/ \;

FROM ubuntu-https AS sampler-assets
COPY docker/apt-install.sh /usr/local/bin/apt-install.sh
RUN sh /usr/local/bin/apt-install.sh python3 ca-certificates
WORKDIR /provision
COPY scripts/provision-samplers.py scripts/provision-samplers.py
COPY src/midimcp/sampler_assets src/midimcp/sampler_assets
RUN python3 scripts/provision-samplers.py /samplers

# MidiMCP: retro MIDI composer — MCP server, web UI and FluidSynth renderer.
# Ubuntu 24.04 base: FluidSynth 2.3.4 + FluidR3 GM, the exact versions the render
# determinism tests and docs/reference/08-soundbanks.md checksum were verified against.
FROM ubuntu-https

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
    MIDIMCP_PORT=8765 \
    MIDIMCP_SAMPLER_DIR=/usr/share/midimcp/samplers \
    MIDIMCP_SFIZZ=/usr/local/bin/sfizz_render

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

COPY --from=sfizz-build /build/out/library/bin/sfizz_render /usr/local/bin/sfizz_render
COPY --from=sfizz-build /notices /usr/share/doc/sfizz
COPY --from=sampler-assets /samplers /usr/share/midimcp/samplers
RUN /usr/local/bin/sfizz_render --help >/dev/null

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

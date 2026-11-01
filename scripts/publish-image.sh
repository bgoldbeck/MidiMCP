#!/usr/bin/env bash
# Build the MidiMCP Docker image and push it to GitHub Container Registry (ghcr.io).
# Free for public images; runs on your own machine (e.g. the TrueNAS shell), no GitHub Actions.
#
#   sudo bash scripts/publish-image.sh            # prompts for a GitHub token
#   GHCR_OWNER=someone bash scripts/publish-image.sh
#   REFRESH_BASE=1 sudo -E bash scripts/publish-image.sh   # also take Ubuntu security updates (full upload)
#
# Token: GitHub -> Settings -> Developer settings -> Personal access tokens (classic)
#        -> scope "write:packages". It is used once for `docker login` and not stored by this script.
set -euo pipefail

OWNER="${GHCR_OWNER:-bgoldbeck}"
OWNER="$(printf '%s' "$OWNER" | tr '[:upper:]' '[:lower:]')"
IMAGE="ghcr.io/${OWNER}/midimcp"

cd "$(dirname "$0")/.."
VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n 1)"
COMMIT="$(git rev-parse --short HEAD)"

if [ -n "$(git status --porcelain)" ]; then
  echo "error: uncommitted changes in $(pwd); commit or stash them so the image matches a commit." >&2
  exit 1
fi

# Upload size: only changed layers are pushed (see the layer notes in the Dockerfile).
#  - The Ubuntu base is NOT re-pulled by default: a newer base would rebuild and re-upload
#    every layer (~300 MB). Set REFRESH_BASE=1 now and then to take Ubuntu security updates.
#  - --cache-from reuses the layers already on ghcr.io even if the local build cache was
#    cleaned, so unchanged layers stay byte-identical and are not uploaded again.
build_args=(--platform linux/amd64 --build-arg BUILDKIT_INLINE_CACHE=1)
if [ "${REFRESH_BASE:-0}" = "1" ]; then
  echo "REFRESH_BASE=1: pulling the latest Ubuntu base; every layer is rebuilt and uploaded."
  build_args+=(--pull)
else
  build_args+=(--cache-from "${IMAGE}:latest")
fi

echo "Building ${IMAGE} (version ${VERSION}, commit ${COMMIT})"
DOCKER_BUILDKIT=1 docker build "${build_args[@]}" \
  -t "${IMAGE}:${VERSION}" -t "${IMAGE}:${COMMIT}" -t "${IMAGE}:latest" .

if [ -z "${GHCR_TOKEN:-}" ]; then
  echo "Paste the token and press Enter (input is hidden; in a browser shell use Ctrl+Shift+V or right-click > Paste)."
  read -r -s -p "GitHub token with write:packages for ${OWNER}: " GHCR_TOKEN
  echo
fi
GHCR_TOKEN="$(printf '%s' "${GHCR_TOKEN}" | tr -d '[:space:]')"
if [ -z "${GHCR_TOKEN}" ]; then
  echo "error: no token received (the paste did not arrive). Run again and paste with Ctrl+Shift+V or right-click > Paste." >&2
  echo "       The image is already built and cached, so the rerun is quick." >&2
  exit 1
fi
echo "Token received (${#GHCR_TOKEN} characters). Logging in to ghcr.io..."
printf '%s' "${GHCR_TOKEN}" | docker login ghcr.io -u "${OWNER}" --password-stdin
trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT

for tag in "${VERSION}" "${COMMIT}" latest; do
  docker push "${IMAGE}:${tag}"
done

echo
echo "Published ${IMAGE}:latest (${VERSION}, ${COMMIT})."
echo "First time only: make the package public at https://github.com/users/${OWNER}/packages/container/midimcp/settings"
echo "(Danger Zone -> Change visibility -> Public) so TrueNAS can pull it without logging in."

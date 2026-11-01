#!/usr/bin/env bash
# Build the MidiMCP Docker image and push it to GitHub Container Registry (ghcr.io).
# Free for public images; runs on your own machine (e.g. the TrueNAS shell), no GitHub Actions.
#
#   sudo bash scripts/publish-image.sh            # prompts for a GitHub token
#   GHCR_OWNER=someone bash scripts/publish-image.sh
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

echo "Building ${IMAGE} (version ${VERSION}, commit ${COMMIT})"
docker build --pull --platform linux/amd64 \
  -t "${IMAGE}:${VERSION}" -t "${IMAGE}:${COMMIT}" -t "${IMAGE}:latest" .

if [ -z "${GHCR_TOKEN:-}" ]; then
  read -r -s -p "GitHub token with write:packages for ${OWNER}: " GHCR_TOKEN
  echo
fi
printf '%s' "${GHCR_TOKEN}" | docker login ghcr.io -u "${OWNER}" --password-stdin
trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT

for tag in "${VERSION}" "${COMMIT}" latest; do
  docker push "${IMAGE}:${tag}"
done

echo
echo "Published ${IMAGE}:latest (${VERSION}, ${COMMIT})."
echo "First time only: make the package public at https://github.com/users/${OWNER}/packages/container/midimcp/settings"
echo "(Danger Zone -> Change visibility -> Public) so TrueNAS can pull it without logging in."

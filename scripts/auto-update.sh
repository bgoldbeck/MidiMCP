#!/usr/bin/env bash
# Nightly auto-update for TrueNAS (run as root from System -> Advanced -> Cron Jobs):
#   1. git pull the latest main into this checkout
#   2. if there is a commit that has not been published yet:
#        build + push ghcr.io/<owner>/midimcp (scripts/publish-image.sh)
#        redeploy the TrueNAS app so it pulls the new image
#   3. otherwise do nothing
#
# Cron command:   bash /mnt/POOL/midimcp/src/scripts/auto-update.sh
#
# Settings (environment variables, all optional):
#   GHCR_TOKEN_FILE  file holding the GitHub token (default: <checkout>/../ghcr-token, mode 600)
#   APP_NAME         TrueNAS app to redeploy (default: midimcp)
#   STATE_DIR        where the log and last-published marker live (default: <checkout>/..)
#   FORCE=1          publish even if the commit was already published
#   REFRESH_BASE=1   pull the latest Ubuntu base (security updates; uploads every layer)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${STATE_DIR:-$(dirname "$REPO_DIR")}"
TOKEN_FILE="${GHCR_TOKEN_FILE:-$STATE_DIR/ghcr-token}"
APP_NAME="${APP_NAME:-midimcp}"
LOG_FILE="$STATE_DIR/auto-update.log"
MARKER="$STATE_DIR/last-published-commit"
LOCK="$STATE_DIR/auto-update.lock"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

fail() {
  log "ERROR: $*"
  exit 1
}

# Only one run at a time (a slow build must not overlap the next cron run).
exec 9>"$LOCK"
if ! flock -n 9; then
  log "another auto-update is still running; skipping"
  exit 0
fi

log "---- auto-update start ($REPO_DIR)"

[ -f "$TOKEN_FILE" ] || fail "token file $TOKEN_FILE not found (see docs/deploy/auto-update.md)"
mode="$(stat -c '%a' "$TOKEN_FILE")"
[ "$mode" = "600" ] || [ "$mode" = "400" ] || fail "token file $TOKEN_FILE must be mode 600 (is $mode): chmod 600 $TOKEN_FILE"

cd "$REPO_DIR"
git fetch --quiet origin main || fail "git fetch failed (network?)"
if [ -n "$(git status --porcelain)" ]; then
  fail "checkout has local changes; refusing to update. Inspect with: cd $REPO_DIR && git status"
fi
git merge --ff-only --quiet origin/main || fail "cannot fast-forward to origin/main (local commits?)"

commit="$(git rev-parse HEAD)"
short="$(git rev-parse --short HEAD)"
last="$(cat "$MARKER" 2>/dev/null || true)"
if [ "$commit" = "$last" ] && [ "${FORCE:-0}" != "1" ]; then
  log "already published $short; nothing to do"
  exit 0
fi

last_short="${last:0:7}"
log "new commit $short (last published: ${last_short:-none}); building and publishing"
GHCR_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
[ -n "$GHCR_TOKEN" ] || fail "token file $TOKEN_FILE is empty"
export GHCR_TOKEN
if ! bash scripts/publish-image.sh >>"$LOG_FILE" 2>&1; then
  fail "publish failed; see $LOG_FILE"
fi
unset GHCR_TOKEN
printf '%s\n' "$commit" > "$MARKER"
log "published $short"

redeploy() {
  # TrueNAS 25.10+ uses `call -j`; older releases use `call -job`.
  midclt call -j app.redeploy "$APP_NAME" >>"$LOG_FILE" 2>&1 \
    || midclt call -job app.redeploy "$APP_NAME" >>"$LOG_FILE" 2>&1
}

if command -v midclt >/dev/null 2>&1; then
  if redeploy; then
    log "redeployed TrueNAS app '$APP_NAME'"
  else
    fail "published, but redeploying app '$APP_NAME' failed; press Update/Restart in Apps (see $LOG_FILE)"
  fi
else
  log "midclt not found (not TrueNAS?); published only, restart the app yourself"
fi

docker image prune -f >/dev/null 2>&1 || true
log "---- auto-update done"

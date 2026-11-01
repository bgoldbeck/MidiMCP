# Automatic nightly updates on TrueNAS

[`scripts/auto-update.sh`](../../scripts/auto-update.sh) keeps the NAS on the latest code with no GitHub Actions:

1. `git pull` the newest `main` into the checkout on the NAS.
2. If that commit was not published yet: build + push `ghcr.io/<owner>/midimcp` (via `publish-image.sh`), then redeploy the TrueNAS app so it pulls the new image (`midclt call -job app.redeploy midimcp`).
3. Otherwise: do nothing.

Assumes the layout from [truenas.md](truenas.md): checkout at `/mnt/POOL/midimcp/src`, app named `midimcp` installed with `pull_policy: always`. Replace `POOL` below.

## 1. Save your GitHub token on the NAS (once)

A classic token with only the `write:packages` scope. Paste with **Ctrl+Shift+V** (input is hidden), then Enter:

```bash
sudo bash -c 'umask 077; read -r -s -p "GitHub token: " t; printf "%s\n" "$t" > /mnt/POOL/midimcp/ghcr-token; echo; wc -c < /mnt/POOL/midimcp/ghcr-token'
```

It prints the character count (41 for a classic `ghp_` token). The file is readable by root only and lives outside the folder the container mounts.

## 2. Test it once by hand

```bash
sudo bash /mnt/POOL/midimcp/src/scripts/auto-update.sh
```

The first run publishes (a few minutes) and redeploys the app. A second run should say `nothing to do`.

## 3. Schedule it

**System** → **Advanced Settings** → **Cron Jobs** → **Add**:

| Field | Value |
|---|---|
| Description | `MidiMCP auto-update` |
| Command | `bash /mnt/POOL/midimcp/src/scripts/auto-update.sh` |
| Run As User | `root` |
| Schedule | Daily (or Custom `0 4 * * *` for 04:00) |
| Hide Standard Output | ✔ (quiet on success) |
| Hide Standard Error | ✘ (failures reach your TrueNAS alert email) |
| Enabled | ✔ |

## Logs and controls

- Log: `/mnt/POOL/midimcp/auto-update.log` (includes the full build output).
- Last published commit: `/mnt/POOL/midimcp/last-published-commit`.
- Force a rebuild of the same commit: `sudo FORCE=1 bash /mnt/POOL/midimcp/src/scripts/auto-update.sh`.
- Runs never overlap (lock file); a slow build simply makes the next run skip.

## Safety rules built in

- Refuses to run if the token file is missing or not mode 600.
- Refuses to touch a checkout with local edits, and only fast-forwards (never rewrites history).
- Marks a commit published only after the push succeeded; a failed publish is retried next night.
- Reports a failed redeploy instead of hiding it (the image is still published; press **Update** in Apps).
- Prunes dangling Docker images after each update so old builds don't fill the boot pool.

## Turning it off

Disable or delete the cron job, and remove the token: `sudo rm /mnt/POOL/midimcp/ghcr-token`. Revoke the token on GitHub if you no longer need it.

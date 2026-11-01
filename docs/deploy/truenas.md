# Deploy MidiMCP on TrueNAS SCALE

Two steps: make a dataset, paste one YAML. Menus are for SCALE 24.10 "Electric Eel" and later (Docker-based apps); names can shift slightly between releases.

## 1. Make a dataset

**Datasets** → select your pool → **Add Dataset** → name `midimcp`, preset **Apps** → **Save**.

It appears at `/mnt/<your-pool>/midimcp`. The *Apps* preset lets the container user (`apps`, UID 568) write there.

## 2. Install the app

**Apps** → **Discover Apps** → three-dot menu → **Install via YAML** → name `midimcp` → paste [`truenas-app.yaml`](truenas-app.yaml), changing only `YOUR_POOL` on the `volumes:` line → **Save**.

```yaml
services:
  midimcp:
    image: ghcr.io/bgoldbeck/midimcp:latest
    pull_policy: always
    restart: unless-stopped
    user: "568:568"
    ports:
      - "8765:8765"
    volumes:
      - /mnt/YOUR_POOL/midimcp:/data
```

If port 8765 is taken, change only the left number (e.g. `"8770:8765"`).

## 3. Get your access token

On first start the app generates a token. Find it in **Apps** → `midimcp` → **Logs** (the line after "Generated access token"), or in the shell:

```bash
sudo cat /mnt/YOUR_POOL/midimcp/token.txt
```

Your AI clients need it: [../agents/connect-agents.md](../agents/connect-agents.md). To use your own token instead, add `environment: { MIDIMCP_TOKEN: "<at least 16 chars>" }` to the YAML.

## 4. Open the web interface

Browse to `http://<nas-ip>:8765/` and paste the access token once (the browser remembers it; **Forget token** clears it). You get the song library, playback with loop and speed, an overview, tracks (instrument, volume, mute), checks and exports. Edits made by your AI client appear live.

## 5. Check it

From your PC:

```bash
curl http://<nas-ip>:8765/healthz
```

Expect `{"status":"ok",...,"audio":true,"auth":true}`. Optional full test (needs this repo + Python on your PC):

```bash
python scripts/smoke_test.py --url http://<nas-ip>:8765 --token YOUR_TOKEN
```

## Where the image comes from

`ghcr.io/bgoldbeck/midimcp` is published by hand — no paid GitHub services.

**Windows PC** (Docker Desktop + Git for Windows): double-click [`scripts/publish-image.cmd`](../../scripts/publish-image.cmd) in your clone. It checks Docker, your checkout (offers `git pull` if behind), builds with live colored output (errors in red, saved to `publish-image.log`), asks for your GitHub token (hidden), pushes, and logs out. `scripts\publish-image.cmd -NoPush` only builds.

**Linux / the TrueNAS shell:** [`scripts/publish-image.sh`](../../scripts/publish-image.sh):

```bash
git clone https://github.com/bgoldbeck/MidiMCP.git && cd MidiMCP && sudo bash scripts/publish-image.sh
```

It builds, asks for a GitHub token with the `write:packages` scope (GitHub → Settings → Developer settings → Personal access tokens), and pushes `latest`, the version and the commit tags. The first time, make the package **public** (link printed at the end) so TrueNAS can pull without credentials. The image contains no secrets.

**Automatic nightly updates:** see [auto-update.md](auto-update.md).

No published image yet? Use [`truenas-app-build-from-github.yaml`](truenas-app-build-from-github.yaml) instead: TrueNAS builds straight from the GitHub repo (a few minutes on first install).

## Updating

Publish a new image (above), then **Apps** → `midimcp` → **Update** / **Restart** (`pull_policy: always` fetches the new `latest`). Songs are untouched; the store format is versioned and unknown versions are refused rather than misread.

## What lives in the dataset

| Path | Contents | Safe to delete? |
|---|---|---|
| `projects/` | Songs and every revision (source of truth) | **No** |
| `trash/` | Songs deleted in the web UI (move a folder back into `projects/`, renamed to its original ID, to restore) | Yes, to free space for good |
| `token.txt` | Access token | Delete + restart to get a new token |
| `library.sqlite` | Search index | Yes (rebuilt automatically) |
| `renders/` | Rendered WAV cache | Yes |
| `banks/`, `bank-registry.json` | Your imported SoundFonts | Only if you no longer need them |

Back up with normal TrueNAS **periodic snapshots** / replication of the `midimcp` dataset.

## Troubleshooting

- Logs say `cannot read or create /data/token.txt`: the container user can't write the dataset. Shell: `sudo chown -R 568:568 /mnt/YOUR_POOL/midimcp`, then restart the app.
- `audio: false` in `/healthz`: the image is broken or not the published one; republish or use the build-from-GitHub YAML.

## Security

- The token protects everything except `/healthz`.
- Do **not** port-forward 8765 to the internet. For access away from home use a VPN (e.g. the Tailscale app on TrueNAS).
- Optional: `MIDIMCP_ALLOWED_HOSTS=truenas.local:8765,192.168.1.140:8765` also enforces Host/Origin checks on `/mcp`.

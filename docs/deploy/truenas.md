# Deploy MidiMCP on TrueNAS SCALE

Tested container behavior: Ubuntu 24.04 image, FluidSynth 2.3.4, FluidR3 GM, runs as UID/GID 568 (TrueNAS `apps`). TrueNAS menus below are for SCALE 24.10 "Electric Eel" and later (Docker-based apps); names can shift slightly between releases.

## 1. Make a dataset

Storage → your pool → **Add Dataset** → name `apps/midimcp` (preset *Apps*). Inside it create a child dataset or folder `data`.

Give the `apps` user (UID 568) ownership of `data`: Datasets → `apps/midimcp/data` → **Edit Permissions** → owner user/group `apps`, apply recursively.

Result: `/mnt/POOL/apps/midimcp/data` (replace `POOL` with your pool name everywhere below).

## 2. Pick a token

Any long random string. On the NAS shell or your PC:

```bash
openssl rand -hex 32
```

Keep it; your AI clients need it too.

## 3. Build the image on the NAS

System → **Shell** (or SSH in as an admin):

```bash
cd /mnt/POOL/apps/midimcp
```

```bash
sudo git clone https://github.com/bgoldbeck/MidiMCP.git src
```

```bash
cd src && sudo docker build -t midimcp:latest .
```

(No hosted CI or registry is used; the image is built locally. Alternatively build on your PC and push to a registry of your choice, then change `image:` in the YAML.)

## 4. Install the app

Apps → **Discover Apps** → three-dot menu → **Install via YAML**. Name it `midimcp` and paste [`truenas-app.yaml`](truenas-app.yaml) with your pool path and token filled in. Save.

## 5. Check it

From your PC:

```bash
curl http://truenas.local:8765/healthz
```

Expect `{"status":"ok","version":"0.1.0","audio":true,"auth":true}`. Then run the full end-to-end check (needs this repo and Python on your PC, `python -m pip install -e ".[dev]"`):

```bash
python scripts/smoke_test.py --url http://truenas.local:8765 --token YOUR_TOKEN
```

It composes a 4-bar test song, renders it, and downloads the `.mid` and `.wav` into `smoke-output/`.

## 6. Connect your AI client

See [../agents/connect-agents.md](../agents/connect-agents.md).

## Updating

```bash
cd /mnt/POOL/apps/midimcp/src && sudo git pull && sudo docker build -t midimcp:latest .
```

Then Apps → `midimcp` → **Restart**. Songs in `data/` are untouched; the store format is versioned and unknown versions are refused rather than misread.

## What lives in `data/`

| Path | Contents | Safe to delete? |
|---|---|---|
| `projects/` | Songs and every revision (source of truth) | **No** |
| `library.sqlite` | Search index | Yes (rebuilt automatically) |
| `renders/` | Rendered WAV cache | Yes |
| `banks/`, `bank-registry.json` | Your imported SoundFonts | Only if you no longer need them |

Back up with normal TrueNAS **periodic snapshots** / replication of `apps/midimcp/data`.

## Security

- The token protects everything except `/healthz`. Without `MIDIMCP_TOKEN` the container refuses to start.
- Do **not** port-forward 8765 to the internet. For access away from home use a VPN (e.g. the Tailscale app on TrueNAS).
- Optional: set `MIDIMCP_ALLOWED_HOSTS=truenas.local:8765,192.168.1.10:8765` to also enforce Host/Origin checks on `/mcp`.

#!/usr/bin/env python3
"""Provision the pinned CC0 flute subset at install/build time (never playback).

Run: python scripts/provision-samplers.py DEST [--local-source VSCO-Flute]
Existing correct files are reused; every byte is checked before atomic replacement.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path


def provision(destination: Path, local_source: Path | None = None) -> None:
    assets = Path(__file__).resolve().parents[1] / "src/midimcp/sampler_assets"
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    files = {}
    for patch in manifest["patches"]:
        files.update(patch["files"])
    destination.mkdir(parents=True, exist_ok=True)

    def install(item):
        name, expected = item
        target = destination / name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            return
        if (assets / name).is_file():
            content = (assets / name).read_bytes()
        elif local_source is not None:
            content = (local_source / name).read_bytes()
        else:
            url = (
                "https://raw.githubusercontent.com/sgossner/VSCO-2-CE/"
                + manifest["revision"]
                + "/"
                + name
            )
            with urllib.request.urlopen(url, timeout=120) as response:
                content = response.read()
        if hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError(f"checksum mismatch for {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(install, sorted(files.items())))
    shutil.copyfile(assets / "manifest.json", destination / "manifest.json")
    print(f"Verified {len(files)} files in {destination}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--local-source", type=Path)
    args = parser.parse_args()
    provision(args.destination, args.local_source)

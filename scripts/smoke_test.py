"""End-to-end check of a running MidiMCP server over HTTP MCP.

Usage (from any machine with the repo's Python deps installed):

    python scripts/smoke_test.py --url http://truenas.local:8765 --token "$MIDIMCP_TOKEN"

It creates a short song titled "MidiMCP Smoke Test" (a new project each run),
renders a preview, exports MIDI and WAV, and downloads them to ./smoke-output/.
When the server reports audio unavailable, only composition and MIDI are checked.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


async def call(client: Client, tool: str, **args: Any) -> dict:
    result = await client.call_tool(tool, args)
    if result.is_error:
        raise SystemExit(f"{tool} failed: {result.content[0].text}")
    return result.structured_content


async def run(url: str, token: str, out: Path) -> None:
    health = httpx.get(f"{url}/healthz", timeout=10).json()
    print("health:", health)
    unauthorized = httpx.post(f"{url}/mcp", json={}, timeout=10).status_code
    assert unauthorized == 401, f"expected 401 without token, got {unauthorized}"
    print("auth: requests without token are rejected (401)")

    http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with http, Client(streamable_http_client(f"{url}/mcp", http_client=http)) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        print(f"tools ({len(tools)}):", ", ".join(tools))
        song = await call(
            client,
            "create_project",
            title="MidiMCP Smoke Test",
            tempo_bpm=84,
            meter_numerator=6,
            meter_denominator=8,
            tonic="G#",
            bars=4,
            percussion_allowed=False,
            tags=["smoke-test"],
            operation_id=f"smoke-{time.time_ns()}",
        )
        pid, rev = song["projectId"], song["revision"]
        print("created:", pid, song["key"], song["timing"])
        rev = (
            await call(
                client,
                "add_track",
                project_id=pid,
                expected_revision=rev,
                instrument_id="retro.wooden_flute",
                name="Flute",
                track_id="flute",
            )
        )["revision"]
        rev = (
            await call(
                client,
                "add_track",
                project_id=pid,
                expected_revision=rev,
                instrument_id="retro.lute",
                name="Lute",
                track_id="lute",
            )
        )["revision"]
        melody = [68, 70, 72, 75, 73, 72, 70, 68]
        flute = [
            {"pitch": p, "startTick": i * 1440, "durationTicks": 1320, "velocity": 78}
            for i, p in enumerate(melody)
        ]
        chords = [(56, 60, 63), (53, 56, 60), (49, 53, 56), (51, 55, 58)]
        lute = [
            {"pitch": p, "startTick": bar * 2880 + k * 480, "durationTicks": 480, "velocity": 62}
            for bar, chord in enumerate(chords)
            for k, p in enumerate(chord * 2)
        ]
        rev = (
            await call(
                client,
                "replace_notes",
                project_id=pid,
                expected_revision=rev,
                track_id="flute",
                start_bar=1,
                end_bar=4,
                notes=flute,
            )
        )["revision"]
        result = await call(
            client,
            "replace_notes",
            project_id=pid,
            expected_revision=rev,
            track_id="lute",
            start_bar=1,
            end_bar=4,
            notes=lute,
        )
        print("revision", result["revision"], "-", result["changes"]["text"])
        report = await call(client, "validate_project", project_id=pid)
        print("validation ok:", report["ok"], "warnings:", [w["code"] for w in report["warnings"]])
        midi = await call(client, "export_project", project_id=pid, format="midi")
        exports = [midi]
        if health.get("audio"):
            job = await call(client, "render_preview", project_id=pid)
            print("render:", json.dumps(job.get("render") or job))
            exports.append(await call(client, "export_project", project_id=pid, format="wav"))
        else:
            print("Audio unavailable: skipped preview and WAV; checking composition and MIDI only.")

    out.mkdir(exist_ok=True)
    for item in exports:
        response = httpx.get(
            f"{url}{item['downloadPath']}", headers={"Authorization": f"Bearer {token}"}, timeout=60
        )
        response.raise_for_status()
        (out / item["file"]).write_bytes(response.content)
        print(f"downloaded {out / item['file']} ({len(response.content)} bytes)")
    print("SMOKE TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="e.g. http://truenas.local:8765")
    parser.add_argument("--token", required=True)
    parser.add_argument("--out", default="smoke-output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.url.rstrip("/"), args.token, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

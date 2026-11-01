"""JSON Schema export for score and brief documents.

Checked-in copies live in ``schemas/``; regenerate with
``python -m midimcp.model.schema``. A test fails if they drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from midimcp.model.brief import BRIEF_SCHEMA_VERSION, Brief
from midimcp.model.score import SCORE_SCHEMA_VERSION, Score

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"


def score_json_schema() -> dict:
    schema = Score.model_json_schema(by_alias=True)
    schema["$id"] = f"midimcp:score:{SCORE_SCHEMA_VERSION}"
    return schema


def brief_json_schema() -> dict:
    schema = Brief.model_json_schema(by_alias=True)
    schema["$id"] = f"midimcp:brief:{BRIEF_SCHEMA_VERSION}"
    return schema


def schema_files() -> dict[str, dict]:
    return {
        f"score-{SCORE_SCHEMA_VERSION}.schema.json": score_json_schema(),
        f"brief-{BRIEF_SCHEMA_VERSION}.schema.json": brief_json_schema(),
    }


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_schema_files(directory: Path = SCHEMA_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in schema_files().items():
        path = directory / name
        path.write_text(render(schema), encoding="utf-8", newline="\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_schema_files():
        sys.stdout.write(f"wrote {path}\n")

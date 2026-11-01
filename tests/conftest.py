from __future__ import annotations

import copy

import pytest

# 6/8 at 84 quarter-BPM, 960 PPQ: 2880 ticks per bar, 8 bars.
BAR = 2880


def lanterns_score_dict() -> dict:
    """Small valid two-track score used across tests (Ab major, no percussion)."""
    return copy.deepcopy(
        {
            "schemaVersion": "1.0.0",
            "projectId": "lanterns-of-the-vale",
            "revision": 0,
            "metadata": {"title": "Lanterns of the Vale", "usage": "sparkfall.town.day"},
            "timeline": {
                "ppq": 960,
                "tempoUsPerQuarter": 714286,
                "meter": {"numerator": 6, "denominator": 8},
                "totalTicks": 8 * BAR,
                "loop": {"enabled": True, "startTick": 0, "endTick": 8 * BAR},
            },
            "tonality": {
                "tonicPitchClass": 8,
                "mode": "ionian",
                "requestedSpelling": "G#",
                "displaySpelling": "Ab",
            },
            "soundProfile": {"profileId": "retro-gm-1997-v1", "bankId": "retro-gm-default"},
            "tracks": [
                {
                    "id": "flute-1",
                    "name": "Wooden Flute",
                    "instrumentId": "retro.wooden_flute",
                    "gainDb": -3.0,
                    "notes": [
                        {
                            "id": "f1",
                            "pitch": 68,
                            "startTick": 0,
                            "durationTicks": 720,
                            "velocity": 80,
                        },
                        {
                            "id": "f2",
                            "pitch": 70,
                            "startTick": 960,
                            "durationTicks": 480,
                            "velocity": 76,
                        },
                        {
                            "id": "f3",
                            "pitch": 72,
                            "startTick": 1440,
                            "durationTicks": 1440,
                            "velocity": 74,
                        },
                        {
                            "id": "f4",
                            "pitch": 75,
                            "startTick": 4 * BAR,
                            "durationTicks": 1440,
                            "velocity": 72,
                        },
                    ],
                },
                {
                    "id": "lute-1",
                    "name": "Medieval Lute",
                    "instrumentId": "retro.lute",
                    "gainDb": -6.0,
                    "pan": -0.15,
                    "notes": [
                        {
                            "id": "l1",
                            "pitch": 56,
                            "startTick": 0,
                            "durationTicks": 960,
                            "velocity": 66,
                        },
                        {
                            "id": "l2",
                            "pitch": 60,
                            "startTick": 0,
                            "durationTicks": 960,
                            "velocity": 63,
                        },
                        {
                            "id": "l3",
                            "pitch": 63,
                            "startTick": 0,
                            "durationTicks": 960,
                            "velocity": 61,
                        },
                    ],
                },
            ],
            "sections": [
                {"id": "section-a", "label": "A", "startTick": 0, "endTick": 4 * BAR},
                {"id": "section-b", "label": "B", "startTick": 4 * BAR, "endTick": 8 * BAR},
            ],
            "harmony": [
                {"startTick": 0, "durationTicks": BAR, "symbol": "Ab", "romanNumeral": "I"},
                {"startTick": 7 * BAR, "durationTicks": BAR, "symbol": "Ab", "romanNumeral": "I"},
            ],
        }
    )


@pytest.fixture
def score_dict() -> dict:
    return lanterns_score_dict()

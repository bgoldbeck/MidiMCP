from __future__ import annotations

import os
from pathlib import Path

import pytest

from midimcp.model import Score
from midimcp.soundbanks import (
    DEFAULT_BANK_ID,
    BankChecksumMismatch,
    BankNotFound,
    BankUnavailable,
    InvalidSoundfont,
    PresetMissing,
    SoundbankError,
    SoundbankRegistry,
    read_sf2_presets,
    sha256_file,
    sound_profile_issues,
)
from tests.sf2 import full_gm_presets, write_fake_sf2

REAL_FLUIDR3 = Path("/usr/share/sounds/sf2/FluidR3_GM.sf2")


@pytest.fixture
def system_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "system"
    directory.mkdir()
    write_fake_sf2(directory / "FluidR3_GM.sf2", full_gm_presets())
    return directory


@pytest.fixture
def registry(tmp_path: Path, system_dir: Path) -> SoundbankRegistry:
    return SoundbankRegistry(tmp_path / "data", system_dir=system_dir)


def test_read_presets(tmp_path: Path) -> None:
    path = write_fake_sf2(tmp_path / "a.sf2", [("Flute", 0, 73), ("Kit", 128, 0)])
    assert [(p.name, p.bank, p.program) for p in read_sf2_presets(path)] == [
        ("Flute", 0, 73),
        ("Kit", 128, 0),
    ]
    bad = tmp_path / "bad.sf2"
    bad.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    with pytest.raises(InvalidSoundfont):
        read_sf2_presets(bad)


def test_default_system_bank(registry: SoundbankRegistry, system_dir: Path) -> None:
    banks = registry.list_banks()
    assert [b.id for b in banks] == [DEFAULT_BANK_ID]
    bank = banks[0]
    assert bank.available and bank.license == "MIT" and bank.redistributable
    assert bank.sha256 == sha256_file(system_dir / "FluidR3_GM.sf2")
    assert bank.to_dict()["sizeBytes"] > 0


def test_hash_cache_reused(registry: SoundbankRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    registry.require(DEFAULT_BANK_ID)
    calls = []
    monkeypatch.setattr("midimcp.soundbanks.sha256_file", lambda p: calls.append(p) or "x")
    fresh = SoundbankRegistry(registry.data_dir, system_dir=registry.system_dir)
    assert fresh.require(DEFAULT_BANK_ID).sha256 != "x"
    assert calls == []


def test_missing_and_unknown_banks(tmp_path: Path) -> None:
    registry = SoundbankRegistry(tmp_path, system_dir=tmp_path / "nowhere")
    assert registry.list_banks()[0].available is False
    with pytest.raises(BankUnavailable):
        registry.require(DEFAULT_BANK_ID)
    with pytest.raises(BankNotFound):
        registry.get("nope")


def test_checksum_pinning(registry: SoundbankRegistry, system_dir: Path) -> None:
    pinned = registry.require(DEFAULT_BANK_ID).sha256
    registry.require(DEFAULT_BANK_ID, pinned)
    path = system_dir / "FluidR3_GM.sf2"
    write_fake_sf2(path, [("Only", 0, 1)])
    os.utime(path, ns=(1, 1))
    with pytest.raises(BankChecksumMismatch):
        registry.require(DEFAULT_BANK_ID, pinned)


def test_instruments_and_presets(registry: SoundbankRegistry, tmp_path: Path) -> None:
    instruments = registry.instruments(DEFAULT_BANK_ID)
    assert all(i["available"] for i in instruments)
    flute = registry.instruments(DEFAULT_BANK_ID, search="wooden")
    assert [i["id"] for i in flute] == ["retro.wooden_flute"]
    assert flute[0]["presetName"] == "GM 73"
    registry.check_instruments(DEFAULT_BANK_ID, ["retro.lute", "gm.drums", "gm.5"])

    sparse_dir = tmp_path / "sparse"
    sparse_dir.mkdir()
    write_fake_sf2(sparse_dir / "FluidR3_GM.sf2", [("Flute", 0, 73)])
    sparse = SoundbankRegistry(tmp_path / "d2", system_dir=sparse_dir)
    with pytest.raises(PresetMissing):
        sparse.check_instruments(DEFAULT_BANK_ID, ["retro.lute"])


def test_user_bank_registration(registry: SoundbankRegistry) -> None:
    write_fake_sf2(registry.banks_dir / "retro.sf2", full_gm_presets())
    record = registry.register_user_bank(
        bank_id="retro-user", filename="retro.sf2", name="My Retro Bank", license="CC-BY-4.0"
    )
    assert record.available and record.source == "user" and not record.redistributable
    reloaded = SoundbankRegistry(registry.data_dir, system_dir=registry.system_dir)
    assert [b.id for b in reloaded.list_banks()] == [DEFAULT_BANK_ID, "retro-user"]
    with pytest.raises(SoundbankError):
        registry.register_user_bank(
            bank_id="retro-user", filename="retro.sf2", name="x", license="x"
        )
    with pytest.raises(SoundbankError):
        registry.register_user_bank(
            bank_id="esc", filename="../system/FluidR3_GM.sf2", name="x", license="x"
        )
    (registry.banks_dir / "notes.txt").write_text("hi")
    with pytest.raises(SoundbankError):
        registry.register_user_bank(bank_id="txt", filename="notes.txt", name="x", license="x")
    registry.remove_user_bank("retro-user")
    assert [b.id for b in registry.list_banks()] == [DEFAULT_BANK_ID]


def test_sound_profile_issues(registry: SoundbankRegistry, score_dict: dict) -> None:
    score_dict["soundProfile"]["bankId"] = DEFAULT_BANK_ID
    assert sound_profile_issues(Score.model_validate(score_dict), registry) == []
    score_dict["soundProfile"]["bankSha256"] = "0" * 64
    issues = sound_profile_issues(Score.model_validate(score_dict), registry)
    assert [i.code for i in issues] == ["BANK_CHECKSUM_MISMATCH"]
    score_dict["soundProfile"] = {"profileId": "p", "bankId": "missing-bank"}
    assert [i.code for i in sound_profile_issues(Score.model_validate(score_dict), registry)] == [
        "BANK_NOT_FOUND"
    ]


@pytest.mark.skipif(not REAL_FLUIDR3.is_file(), reason="FluidR3_GM.sf2 not installed")
def test_real_fluidr3_has_every_builtin_instrument(tmp_path: Path) -> None:
    registry = SoundbankRegistry(tmp_path)
    assert all(i["available"] for i in registry.instruments(DEFAULT_BANK_ID))
    assert registry.get(DEFAULT_BANK_ID).license == "MIT"

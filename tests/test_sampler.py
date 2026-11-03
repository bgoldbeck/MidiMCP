import pytest

from midimcp.sampler import SamplerError, SamplerRegistry


def test_registry_only_accepts_allowlisted_ids(tmp_path, monkeypatch):
    monkeypatch.delenv("MIDIMCP_SAMPLER_DIR", raising=False)
    registry = SamplerRegistry(tmp_path)
    assert {p["id"] for p in registry.list_patches()} == {
        "vsco-flute-controlled",
        "vsco-flute-recorded",
    }
    assert all(not p["available"] for p in registry.list_patches())
    with pytest.raises(SamplerError, match="unknown"):
        registry.require("../flute.sfz")


def test_complete_manifest_is_required_and_hash_is_pinned(tmp_path, monkeypatch):
    monkeypatch.delenv("MIDIMCP_SAMPLER_DIR", raising=False)
    import hashlib
    import json

    from midimcp import sampler

    root = tmp_path / "samplers"
    root.mkdir()
    patch = root / "patch.sfz"
    sample = root / "sample.wav"
    patch.write_bytes(b"<region> sample=sample.wav")
    sample.write_bytes(b"sample")
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [patch, sample]}
    manifest = {
        "patches": [
            {
                "id": "vsco-flute-controlled",
                "name": "Flute",
                "path": "patch.sfz",
                "files": files,
                "controllers": {},
                "description": "test",
            }
        ]
    }
    definition = tmp_path / "manifest.json"
    definition.write_text(json.dumps(manifest))
    monkeypatch.setattr(sampler, "MANIFEST_PATH", definition)
    registry = SamplerRegistry(tmp_path)
    first = registry.require("vsco-flute-controlled")
    assert len(first.sha256) == 64
    assert first.path == patch
    with pytest.raises(SamplerError, match="checksum"):
        registry.require(first.id, "0" * 64)
    sample.write_bytes(b"changed")
    assert not registry.list_patches()[0]["available"]
    with pytest.raises(SamplerError, match="changed"):
        registry.require(first.id, first.sha256)
    sample.unlink()
    with pytest.raises(SamplerError, match="missing"):
        registry.require(first.id)

"""SoundFont bank registry: identity (SHA-256), license metadata, presets.

Banks come from two places:

* **system** banks shipped in the container image (license-audited; see
  ``docs/reference/08-soundbanks.md``), and
* **user** banks the owner places in ``<data>/banks`` and registers through the
  web UI. MCP agents can list banks but never install them.

A score's ``soundProfile.bankId`` must resolve to an available bank, and when a
``bankSha256`` is pinned the file must still match it — the app never silently
substitutes a different bank or preset.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import BinaryIO, Final

from midimcp.instruments import Instrument, builtin_instruments, resolve_instrument
from midimcp.model.score import is_valid_identifier
from midimcp.store.files import atomic_write, pretty_json_bytes

log = logging.getLogger(__name__)

DEFAULT_BANK_ID: Final = "fluidr3-gm"
SYSTEM_SF2_DIR: Final = Path(os.environ.get("MIDIMCP_SYSTEM_SF2_DIR", "/usr/share/sounds/sf2"))


class SoundbankError(ValueError):
    code = "SOUNDBANK_ERROR"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


class BankNotFound(SoundbankError):
    code = "BANK_NOT_FOUND"


class BankUnavailable(SoundbankError):
    code = "BANK_UNAVAILABLE"


class BankChecksumMismatch(SoundbankError):
    code = "BANK_CHECKSUM_MISMATCH"


class InvalidSoundfont(SoundbankError):
    code = "INVALID_SOUNDFONT"


class PresetMissing(SoundbankError):
    code = "PRESET_MISSING"


@dataclass(frozen=True)
class SystemBank:
    id: str
    name: str
    filename: str
    license: str
    author: str
    provenance: str
    redistributable: bool


SYSTEM_BANKS: Final = (
    SystemBank(
        id=DEFAULT_BANK_ID,
        name="FluidR3 GM",
        filename="FluidR3_GM.sf2",
        license="MIT",
        author="Frank Wen and contributors",
        provenance="Debian/Ubuntu package fluid-soundfont-gm (upstream musescore.org)",
        redistributable=True,
    ),
)


@dataclass
class BankRecord:
    id: str
    name: str
    path: str
    source: str  # "system" | "user"
    license: str
    author: str
    provenance: str
    redistributable: bool
    sha256: str | None = None
    size: int | None = None
    mtime_ns: int | None = None
    notes: str = ""
    available: bool = field(default=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "license": self.license,
            "author": self.author,
            "provenance": self.provenance,
            "redistributable": self.redistributable,
            "sha256": self.sha256,
            "sizeBytes": self.size,
            "available": self.available,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Preset:
    name: str
    bank: int
    program: int


def read_sf2_presets(path: Path) -> list[Preset]:
    """Read preset headers (``pdta/phdr``) from an SF2/SF3 file without loading samples."""
    with path.open("rb") as handle:
        riff, _size, form = struct.unpack("<4sI4s", _read_exact(handle, 12))
        if riff != b"RIFF" or form != b"sfbk":
            raise InvalidSoundfont(f"{path.name} is not a SoundFont (missing RIFF/sfbk header)")
        while True:
            header = handle.read(8)
            if len(header) < 8:
                break
            chunk_id, chunk_size = struct.unpack("<4sI", header)
            if chunk_id == b"LIST":
                list_type = _read_exact(handle, 4)
                if list_type == b"pdta":
                    return _read_phdr(handle, chunk_size - 4, path)
                handle.seek(chunk_size - 4 + (chunk_size & 1), os.SEEK_CUR)
            else:
                handle.seek(chunk_size + (chunk_size & 1), os.SEEK_CUR)
    raise InvalidSoundfont(f"{path.name} has no preset data (pdta)")


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise InvalidSoundfont("truncated SoundFont file")
    return data


def _read_phdr(handle: BinaryIO, remaining: int, path: Path) -> list[Preset]:
    end = handle.tell() + remaining
    while handle.tell() < end:
        chunk_id, chunk_size = struct.unpack("<4sI", _read_exact(handle, 8))
        if chunk_id != b"phdr":
            handle.seek(chunk_size + (chunk_size & 1), os.SEEK_CUR)
            continue
        data = _read_exact(handle, chunk_size)
        presets = []
        # 38-byte records; the last one is the terminal "EOP" record.
        for offset in range(0, len(data) - 38, 38):
            name, program, bank = struct.unpack_from("<20sHH", data, offset)
            presets.append(Preset(name.split(b"\0", 1)[0].decode("latin-1").strip(), bank, program))
        return presets
    raise InvalidSoundfont(f"{path.name} has no preset headers (phdr)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class SoundbankRegistry:
    """Registry persisted at ``<data>/bank-registry.json``; system banks are built in."""

    def __init__(
        self,
        data_dir: Path | str,
        *,
        system_dir: Path = SYSTEM_SF2_DIR,
        system_banks: tuple[SystemBank, ...] = SYSTEM_BANKS,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.banks_dir = self.data_dir / "banks"
        self.banks_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.data_dir / "bank-registry.json"
        self.system_dir = system_dir
        self.system_banks = system_banks
        self._preset_cache: dict[tuple[str, str], list[Preset]] = {}

    # ----------------------------------------------------------- persistence

    def _load_user_records(self) -> dict[str, dict]:
        if not self.registry_path.is_file():
            return {}
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return {item["id"]: item for item in data.get("banks", [])}

    def _save_user_records(self, records: dict[str, dict]) -> None:
        payload = {"formatVersion": 1, "banks": sorted(records.values(), key=lambda r: r["id"])}
        atomic_write(self.registry_path, pretty_json_bytes(payload))

    def _records(self) -> list[BankRecord]:
        records = []
        for bank in self.system_banks:
            records.append(
                BankRecord(
                    id=bank.id,
                    name=bank.name,
                    path=str(self.system_dir / bank.filename),
                    source="system",
                    license=bank.license,
                    author=bank.author,
                    provenance=bank.provenance,
                    redistributable=bank.redistributable,
                )
            )
        for item in self._load_user_records().values():
            stored = {k: v for k, v in item.items() if k != "available"}
            records.append(BankRecord(**stored))
        return records

    # ---------------------------------------------------------------- public

    def list_banks(self) -> list[BankRecord]:
        return [self._refresh(record) for record in self._records()]

    def get(self, bank_id: str) -> BankRecord:
        for record in self._records():
            if record.id == bank_id:
                return self._refresh(record)
        raise BankNotFound(f"soundbank {bank_id!r} is not registered; use list_soundbanks")

    def require(self, bank_id: str, expected_sha256: str | None = None) -> BankRecord:
        """Return an available bank, verifying the pinned checksum when given."""
        record = self.get(bank_id)
        if not record.available:
            raise BankUnavailable(
                f"soundbank {bank_id!r} file is missing ({Path(record.path).name}); "
                "reinstall it or remap the project to another bank"
            )
        if expected_sha256 and record.sha256 != expected_sha256:
            raise BankChecksumMismatch(
                f"soundbank {bank_id!r} changed since the project pinned it "
                f"(expected {expected_sha256[:12]}…, found {(record.sha256 or '')[:12]}…); "
                "remap explicitly to accept the new sound"
            )
        return record

    def presets(self, bank_id: str) -> list[Preset]:
        record = self.require(bank_id)
        key = (record.id, record.sha256 or "")
        if key not in self._preset_cache:
            self._preset_cache[key] = read_sf2_presets(Path(record.path))
        return self._preset_cache[key]

    def instruments(self, bank_id: str, search: str | None = None) -> list[dict]:
        """Built-in instrument IDs with availability in this bank."""
        available = {(p.bank, p.program): p.name for p in self.presets(bank_id)}
        results = []
        for instrument in builtin_instruments():
            if search and search.lower() not in f"{instrument.id} {instrument.name}".lower():
                continue
            data = instrument.to_dict()
            preset_name = available.get((instrument.bank, instrument.program))
            data["available"] = preset_name is not None
            data["presetName"] = preset_name
            results.append(data)
        return results

    def check_instruments(self, bank_id: str, instrument_ids: list[str]) -> list[Instrument]:
        """Resolve instruments and ensure each preset exists in the bank (no substitution)."""
        available = {(p.bank, p.program) for p in self.presets(bank_id)}
        resolved = []
        for instrument_id in instrument_ids:
            instrument = resolve_instrument(instrument_id)
            if (instrument.bank, instrument.program) not in available:
                raise PresetMissing(
                    f"soundbank {bank_id!r} has no preset bank {instrument.bank} program "
                    f"{instrument.program} for {instrument_id!r}"
                )
            resolved.append(instrument)
        return resolved

    def register_user_bank(
        self,
        *,
        bank_id: str,
        filename: str,
        name: str,
        license: str,
        author: str = "unknown",
        provenance: str = "user import",
        redistributable: bool = False,
        notes: str = "",
    ) -> BankRecord:
        """Register a SoundFont already placed in ``<data>/banks`` (UI upload, not MCP)."""
        if not is_valid_identifier(bank_id):
            raise SoundbankError(f"invalid bank id {bank_id!r}")
        if any(r.id == bank_id for r in self._records()):
            raise SoundbankError(f"soundbank {bank_id!r} already exists")
        path = (self.banks_dir / filename).resolve()
        if path.parent != self.banks_dir.resolve() or path.suffix.lower() not in {".sf2", ".sf3"}:
            raise SoundbankError("bank file must be an .sf2/.sf3 file directly inside banks/")
        if not path.is_file():
            raise BankUnavailable(f"{filename} not found in banks/")
        read_sf2_presets(path)  # validates the format
        record = BankRecord(
            id=bank_id,
            name=name,
            path=str(path),
            source="user",
            license=license,
            author=author,
            provenance=provenance,
            redistributable=redistributable,
            notes=notes,
        )
        record = self._refresh(record)
        records = self._load_user_records()
        records[bank_id] = {k: v for k, v in asdict(record).items() if k != "available"}
        self._save_user_records(records)
        return record

    def remove_user_bank(self, bank_id: str) -> None:
        records = self._load_user_records()
        if bank_id not in records:
            raise BankNotFound(f"user soundbank {bank_id!r} is not registered")
        del records[bank_id]
        self._save_user_records(records)

    # -------------------------------------------------------------- internals

    def _refresh(self, record: BankRecord) -> BankRecord:
        path = Path(record.path)
        try:
            stat = path.stat()
        except OSError:
            record.available = False
            return record
        record.available = True
        if record.sha256 and record.size == stat.st_size and record.mtime_ns == stat.st_mtime_ns:
            return record
        cached = self._hash_cache().get(record.path)
        if cached and cached["size"] == stat.st_size and cached["mtimeNs"] == stat.st_mtime_ns:
            record.sha256 = cached["sha256"]
        else:
            record.sha256 = sha256_file(path)
            self._store_hash(record.path, stat.st_size, stat.st_mtime_ns, record.sha256)
        record.size, record.mtime_ns = stat.st_size, stat.st_mtime_ns
        return record

    def _hash_cache_path(self) -> Path:
        return self.data_dir / "bank-hashes.json"

    def _hash_cache(self) -> dict:
        try:
            return json.loads(self._hash_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _store_hash(self, path: str, size: int, mtime_ns: int, sha256: str) -> None:
        cache = self._hash_cache()
        cache[path] = {"size": size, "mtimeNs": mtime_ns, "sha256": sha256}
        try:
            atomic_write(self._hash_cache_path(), pretty_json_bytes(cache))
        except OSError:
            log.warning("could not write bank hash cache", exc_info=True)


def sound_profile_issues(score, registry: SoundbankRegistry) -> list:
    """Hard errors for a score's bank: missing, changed, or lacking a needed preset."""
    from midimcp.instruments import UnknownInstrument
    from midimcp.validation import Issue, Severity

    profile = score.sound_profile
    try:
        registry.require(profile.bank_id, profile.bank_sha256)
        available = {(p.bank, p.program) for p in registry.presets(profile.bank_id)}
    except SoundbankError as exc:
        return [Issue(exc.code, Severity.ERROR, str(exc))]
    issues = []
    for track in score.tracks:
        try:
            instrument = resolve_instrument(track.instrument_id)
        except UnknownInstrument:
            continue  # reported by validate_score
        if (instrument.bank, instrument.program) not in available:
            issues.append(
                Issue(
                    PresetMissing.code,
                    Severity.ERROR,
                    f"bank {profile.bank_id!r} has no preset for {track.instrument_id!r}",
                    track_id=track.id,
                )
            )
    return issues

"""Quarantine archive validation and fixed 100-game arena scoring.

Accepted upload: ZIP with a Linux x86_64 ELF at the ROOT named 'engine',
plus at most five regular .nnue files at the root. No scripts, symlinks,
directories, special files or nested paths are accepted. Validation alone
does not make untrusted binaries safe: execute only in an isolated VM with
a rootless container runtime, no network, and strict resource limits.
"""
import hashlib
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

GAMES = 100
PASS_SCORE_X2 = 110  # 55 wins' worth of points in 100 games.
MAX_UPLOAD_BYTES = 128 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 384 * 1024 * 1024
MAX_ENGINE_BYTES = 240 * 1024 * 1024
MAX_FILE_COUNT = 6
MAX_PGN_BYTES = 12 * 1024 * 1024
SAFE_FILE = re.compile(r"^[A-Za-z0-9_.-]{1,75}\.nnue$")


class UnsafeArchive(ValueError):
    """An uploaded archive is not in our minimal, reviewable format."""


@dataclass(frozen=True)
class ValidatedArchive:
    engine_sha256: str
    total_uncompressed: int
    auxiliary_nets: int


def _entries(zf):
    entries = zf.infolist()
    if not 1 <= len(entries) <= MAX_FILE_COUNT:
        raise UnsafeArchive("Archive must contain engine and at most five NNUE files")
    seen, total = set(), 0
    for info in entries:
        name = info.filename
        if name in seen:
            raise UnsafeArchive("Duplicate ZIP entry")
        seen.add(name)
        if name != "engine" and not SAFE_FILE.fullmatch(name):
            raise UnsafeArchive("ZIP files must be engine or root-level *.nnue")
        if info.is_dir() or info.flag_bits & 1:
            raise UnsafeArchive("Directories and encrypted ZIP entries are not permitted")
        if info.file_size > MAX_ENGINE_BYTES or info.file_size < 1:
            raise UnsafeArchive("ZIP contains an empty or oversized file")
        if info.compress_size <= 0 or info.file_size > info.compress_size * 250:
            raise UnsafeArchive("Suspicious ZIP compression ratio")
        # Unix external_attr high word specifies file type; accept regular or
        # unspecified DOS files, reject Unix symlink/device/fifo entries.
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(unix_mode)
        if kind not in (0, stat.S_IFREG):
            raise UnsafeArchive("ZIP contains a symlink or non-regular file")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise UnsafeArchive("Uncompressed ZIP quota exceeded")
    if "engine" not in seen:
        raise UnsafeArchive("ZIP must include a root-level engine file")
    return entries, total


def _elf_header(header):
    if (
        len(header) < 20 or header[:4] != b"\x7fELF"
        or header[4] != 2 or header[5] != 1
        or int.from_bytes(header[18:20], "little") != 62
    ):
        raise UnsafeArchive("engine must be an ELF64 little-endian x86_64 executable")


def validate_archive(archive: Path) -> ValidatedArchive:
    if not archive.is_file() or archive.is_symlink():
        raise UnsafeArchive("Upload is not a regular ZIP file")
    if archive.stat().st_size > MAX_UPLOAD_BYTES:
        raise UnsafeArchive("Compressed upload limit exceeded (128 MiB)")
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            entries, total = _entries(zf)
            digest = hashlib.sha256()
            engine_size = 0
            with zf.open("engine", "r") as reader:
                first = reader.read(64)
                _elf_header(first)
                digest.update(first)
                engine_size += len(first)
                while block := reader.read(1024 * 1024):
                    engine_size += len(block)
                    if engine_size > MAX_ENGINE_BYTES:
                        raise UnsafeArchive("Engine executable too large")
                    digest.update(block)
            # Check CRC and actual sizes for auxiliary NNUE entries as well.
            for info in entries:
                if info.filename == "engine":
                    continue
                observed = 0
                with zf.open(info, "r") as reader:
                    while block := reader.read(1024 * 1024):
                        observed += len(block)
                        if observed > info.file_size:
                            raise UnsafeArchive("NNUE entry changed size during read")
                if observed != info.file_size:
                    raise UnsafeArchive("Truncated NNUE entry")
            return ValidatedArchive(digest.hexdigest(), total, len(entries) - 1)
    except (zipfile.BadZipFile, RuntimeError, EOFError, OSError) as exc:
        raise UnsafeArchive("Invalid or corrupt ZIP archive") from exc


def extract_quarantined(archive: Path, destination: Path) -> ValidatedArchive:
    """Extract only prevalidated filenames, in a private directory.

    No extractall(), user-supplied paths, symlinks, inherited executable bits
    or shell invocations. Files are mounted read-only into the arena container.
    """
    details = validate_archive(archive)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            output = destination / info.filename
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            with os.fdopen(os.open(output, flags, 0o600), "wb") as writer:
                with zf.open(info, "r") as reader:
                    while block := reader.read(1024 * 1024):
                        writer.write(block)
            if output.stat().st_size != info.file_size:
                raise UnsafeArchive("Extracted file has incorrect size")
            output.chmod(0o555 if info.filename == "engine" else 0o444)
    return details


def classify_score(wins: int, draws: int, losses: int) -> dict:
    if any(not isinstance(x, int) or isinstance(x, bool) or x < 0
           for x in (wins, draws, losses)):
        raise ValueError("Non-negative integer W/D/L required")
    if wins + draws + losses != GAMES:
        raise ValueError("Arena results must contain exactly 100 games")
    score_twice = wins * 2 + draws
    return {
        "wins": wins, "draws": draws, "losses": losses,
        "games": GAMES, "score": score_twice / 2,
        "score_percent": score_twice / 2,  # denominator always 100
        "passed": score_twice >= PASS_SCORE_X2,
        "threshold": PASS_SCORE_X2 / 2,
    }

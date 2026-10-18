"""Non-executing identification and staging of user-supplied UCI binaries.

A PE signature or an ELF signature is a format check, NEVER a safety scan.
Windows PE64 EXEs are launched only through a separately configured Wine
container in a disposable Linux VM. No uploaded program runs in the API.
"""
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from arena_core import MAX_UPLOAD_BYTES, UnsafeArchive, extract_quarantined, validate_archive


@dataclass(frozen=True)
class CandidateMetadata:
    platform: str
    engine_sha256: str
    size: int
    archive_type: str


def inspect_windows_exe(path: Path) -> CandidateMetadata:
    """Accept only bounded, genuine PE32+ (x86_64) executables."""
    if path.is_symlink() or not path.is_file():
        raise UnsafeArchive("Not a regular executable file")
    length = path.stat().st_size
    if length < 512 or length > MAX_UPLOAD_BYTES:
        raise UnsafeArchive("Windows EXE must be between 512 bytes and 128 MiB")
    with path.open("rb") as reader:
        mz = reader.read(64)
        if len(mz) != 64 or mz[:2] != b"MZ":
            raise UnsafeArchive("Windows executable must have MZ header")
        pe_offset = int.from_bytes(mz[60:64], "little")
        if not 64 <= pe_offset <= min(1_048_576, length - 26):
            raise UnsafeArchive("Invalid Windows PE offset")
        reader.seek(pe_offset)
        pe = reader.read(26)
        if len(pe) != 26 or pe[:4] != b"PE\x00\x00":
            raise UnsafeArchive("Invalid Windows Portable Executable (PE) header")
        machine = int.from_bytes(pe[4:6], "little")
        if machine == 0x014C:
            raise UnsafeArchive(
                "Windows x86 32-bit EXE detected; only x86_64 PE32+ is supported"
            )
        if machine == 0xAA64:
            raise UnsafeArchive(
                "Windows ARM64 EXE detected; only x86_64 PE32+ is supported"
            )
        if machine != 0x8664:
            raise UnsafeArchive("Unsupported Windows EXE CPU architecture")
        characteristics = int.from_bytes(pe[22:24], "little")
        if characteristics & 0x2000:
            raise UnsafeArchive("This is a Windows DLL, not a runnable EXE")
        if characteristics & 0x1000:
            raise UnsafeArchive("Windows kernel/system executable is not allowed")
        if int.from_bytes(pe[24:26], "little") != 0x020B:
            raise UnsafeArchive("Expected Windows x86_64 PE32+ executable")
        reader.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(block)
    return CandidateMetadata("windows_x86_64", digest.hexdigest(), length, "exe")


def inspect_candidate(path: Path, content_type: str = "") -> CandidateMetadata:
    """Inspect the bytes, not a user-provided name or file extension."""
    with path.open("rb") as f:
        signature = f.read(4)
    if signature.startswith(b"MZ"):
        return inspect_windows_exe(path)
    if signature == b"PK\x03\x04":
        info = validate_archive(path)
        return CandidateMetadata(
            "linux_x86_64", info.engine_sha256,
            path.stat().st_size, "zip"
        )
    raise UnsafeArchive(
        "Upload a Windows x86_64 .exe or a ZIP containing root-level Linux ELF 'engine'"
    )


def stage_candidate(path: Path, destination: Path) -> CandidateMetadata:
    """Stage only validated candidate bytes inside a private directory.

    Must be called on the disposable arena VM; staging is not execution.
    """
    info = inspect_candidate(path)
    if info.platform == "linux_x86_64":
        extract_quarantined(path, destination)
        return info
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    exe = destination / "engine.exe"
    try:
        with path.open("rb") as src, exe.open("xb") as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)
        if inspect_windows_exe(exe).engine_sha256 != info.engine_sha256:
            raise UnsafeArchive("Windows executable changed during staging")
        exe.chmod(0o444)
    except BaseException:
        exe.unlink(missing_ok=True)
        destination.rmdir()
        raise
    return info

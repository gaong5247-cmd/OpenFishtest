"""Archive completed PGN files in daily GitHub Releases.

Run as dry-run: python archive.py
Run for real: python archive.py --apply

Requires: pip install -r requirements-archive.txt
          gh auth login
The script never deletes a local file unless GitHub's asset SHA-256 digest
and byte size match the uploaded compressed archive. Releases are NOT backups.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zstandard import ZstdCompressor

DATA_DIR = Path(os.getenv("OPENFISHTEST_DATA", "data")).resolve()
PGN_DIR = DATA_DIR / "pgn"
STAGING_DIR = DATA_DIR / "archive-staging"
REPO = os.getenv("OPENFISHTEST_ARCHIVE_REPO", "gaong5247-cmd/OpenFishtest")
MAX_BYTES = 5_000_000_000
ARCHIVE_START = 3_000_000_000
ARCHIVE_BATCH_RAW = 25_000_000
STAGING_HEADROOM = 50_000_000
RETENTION = timedelta(days=7)


def data_size():
    return sum(p.stat().st_size for p in DATA_DIR.rglob("*") if p.is_file())


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gh(*args, allow_failure=False):
    try:
        result = subprocess.run(["gh", *args], capture_output=True,
                                text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI (gh) is not installed") from exc
    if result.returncode and not allow_failure:
        raise RuntimeError(result.stderr.strip() or "GitHub command failed")
    return result


def select_files():
    if not PGN_DIR.exists():
        return []
    now = datetime.now(timezone.utc)
    pressure = data_size() >= ARCHIVE_START
    eligible = []
    for path in PGN_DIR.rglob("*.pgn"):
        if not path.is_file() or path.is_symlink():
            continue
        stats = path.stat()
        age = now - datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc)
        # Ignore files potentially still being written by a running worker.
        if age < timedelta(minutes=5):
            continue
        if age >= RETENTION or pressure:
            eligible.append(path)
    return sorted(eligible, key=lambda p: p.stat().st_mtime)


def batches(files):
    batch = []
    batch_size = 0
    for path in files:
        size = path.stat().st_size
        if size > ARCHIVE_BATCH_RAW:
            print(f"SKIP oversized PGN (>25MB): {path}", file=sys.stderr)
            continue
        if batch and (batch_size + size > ARCHIVE_BATCH_RAW or len(batch) >= 80):
            yield batch
            batch = []
            batch_size = 0
        batch.append(path)
        batch_size += size
    if batch:
        yield batch


def create_archive(files):
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    tag = "pgn-archive-" + datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = "games-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") \
               + "-" + uuid.uuid4().hex[:10] + ".tar.zst"
    output = STAGING_DIR / filename
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
    try:
        with output.open("wb") as raw:
            # closefd=False keeps the outer handle owned by 'with'.
            with ZstdCompressor(level=3).stream_writer(raw, closefd=False) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|") as tar:
                    for p in files:
                        tar.add(p, arcname=p.relative_to(PGN_DIR).as_posix(), recursive=False)
        if output.stat().st_size > ARCHIVE_BATCH_RAW:
            raise RuntimeError("Compressed archive exceeds the conservative batch limit")
        return tag, output, before
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def upload_verify(tag, archive):
    if not gh("release", "view", tag, "--repo", REPO, allow_failure=True).returncode == 0:
        gh("release", "create", tag, "--repo", REPO, "--target", "main",
           "--title", "PGN archive " + tag.removeprefix("pgn-archive-"),
           "--notes", "Completed engine-test PGN archive; public historical data.")
    gh("release", "upload", tag, str(archive), "--repo", REPO)
    response = gh("api", f"repos/{REPO}/releases/tags/{tag}")
    data = json.loads(response.stdout)
    asset = next((a for a in data.get("assets", [])
                  if a.get("name") == archive.name and a.get("state") == "uploaded"), None)
    expected = "sha256:" + sha256_file(archive)
    if (not asset or asset.get("digest") != expected or
            asset.get("size") != archive.stat().st_size):
        raise RuntimeError("Remote SHA-256 / size verification failed; local PGNs preserved")
    return asset.get("browser_download_url")


def main():
    parser = argparse.ArgumentParser(description="Verified PGN → GitHub Releases archive")
    parser.add_argument("--apply", action="store_true",
                        help="Actually upload archives and delete verified local PGNs")
    args = parser.parse_args()
    candidates = select_files()
    print(f"Current data: {data_size() / 1e9:.3f} GB; eligible PGNs: {len(candidates)}")
    if not args.apply:
        print("DRY RUN ONLY. Use --apply after gh auth login.")
        return 0
    if not candidates:
        print("Nothing to archive.")
        return 0
    if not shutil.which("gh"):
        print("GitHub CLI not found. No files deleted.", file=sys.stderr)
        return 2
    processed = 0
    for group in batches(candidates):
        if MAX_BYTES - data_size() < STAGING_HEADROOM:
            print("Not enough quota headroom to archive safely. Stop tests and free space.",
                  file=sys.stderr)
            return 2
        tag, archive, original_stats = create_archive(group)
        try:
            url = upload_verify(tag, archive)
            # Remove only source files that have not changed during packaging.
            for p in group:
                if p.exists():
                    actual = (p.stat().st_size, p.stat().st_mtime_ns)
                    if actual == original_stats[p]:
                        p.unlink()
                        processed += 1
                    else:
                        print(f"Preserved changed PGN: {p}", file=sys.stderr)
            print(f"Verified and archived {len(group)} files: {url}")
        except Exception as exc:
            print(f"FAILED: {exc}. Local source files preserved.", file=sys.stderr)
            return 2
        finally:
            # On failure retain staging too, for inspection/retry.
            if processed and archive.exists() and all(not p.exists() for p in group):
                archive.unlink()
    print(f"Archived PGNs removed locally: {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

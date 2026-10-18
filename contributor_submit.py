"""Contributor-side GitHub submission: PGN + EPD only, no server or admin token.

After first-time 'gh auth login', a contributor can push a safe data-only PR:
  python contributor_submit.py --pgn real_games.pgn --epd openings.epd

The maintainer's trusted GitHub Action automatically validates, publishes,
deploys GitHub Pages and closes the PR without a manual review. Nothing
here executes foreign binaries or modifies the main repository directly.

GitHub account + gh CLI + git CLI required on the CONTRIBUTOR's PC.
"""
import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from community_submission import InvalidCommunitySubmission, validate_pair

TARGET = "gaong5247-cmd/OpenFishtest"
GIT_URL = "https://github.com/gaong5247-cmd/OpenFishtest.git"


class SubmissionError(RuntimeError):
    pass


def run(args, cwd=None, env=None):
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False,
        env=env, timeout=120
    )
    if result.returncode:
        details = (result.stderr or result.stdout).strip()[-600:]
        raise SubmissionError(f"{args[0]} command failed: {details}")
    return result.stdout.strip()


def _fork_if_needed(username, env=None):
    fork = f"{username}/OpenFishtest"
    try:
        result = run(
            ["gh", "repo", "view", fork, "--json", "nameWithOwner,parent",
             "--jq", ".parent.nameWithOwner"], env=env
        )
    except SubmissionError:
        run(["gh", "repo", "fork", TARGET, "--clone=false"], env=env)
        return fork
    if result != TARGET:
        raise SubmissionError(
            "Your repository named OpenFishtest is not a fork of the target project"
        )
    return fork


def validate_files(pgn_path, epd_path):
    pgn = Path(pgn_path).expanduser().resolve(strict=True)
    epd = Path(epd_path).expanduser().resolve(strict=True)
    if not pgn.is_file() or not epd.is_file():
        raise InvalidCommunitySubmission("PGN/EPD must be regular files")
    if pgn.suffix.lower() != ".pgn" or epd.suffix.lower() != ".epd":
        raise InvalidCommunitySubmission("Only .pgn + .epd file pairs are accepted")
    # Community GitHub PR files are deliberately small. Raw 200MiB books use
    # the separate HTTPS arena API; Github PR is no replacement for that.
    if pgn.stat().st_size > 2_000_000 or epd.stat().st_size > 512 * 1024:
        raise InvalidCommunitySubmission(
            "GitHub PR limit: PGN 2MB, EPD 512KiB (use normalized book)"
        )
    return validate_pair(pgn.read_bytes(), epd.read_bytes())


def submit(pgn_path, epd_path, progress=print):
    report = validate_files(pgn_path, epd_path)
    progress(
        f"Validated {report.games} real reported games, "
        f"{report.wins}W/{report.draws}D/{report.losses}L, "
        f"{report.epd_positions} opening positions."
    )
    if not shutil.which("gh") or not shutil.which("git"):
        raise SubmissionError("Install GitHub CLI (gh) and Git before uploading")
    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    login = run(["gh", "api", "user", "--jq", ".login"], env=env)
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        raise SubmissionError("Could not identify the authenticated GitHub account")
    # Owner: use the SAME PR-free data-only upload path as the website.
    # Existing gh auth login credentials stay in the local CLI process;
    # a fine-grained PAT does not have to be pasted into a browser.
    if login.casefold() == TARGET.split("/")[0].casefold():
        from community_direct_stage import stage_owner_upload
        token = run(["gh", "auth", "token"], env=env).strip()
        try:
            result = stage_owner_upload(
                token, report.pgn, report.epd,
                uploader=login, progress=progress
            )
        except Exception as exc:
            # Never include the token in an error message or log.
            raise SubmissionError(
                "Owner direct PGN/EPD upload failed: " + str(exc)[:350]
            ) from exc
        progress(
            "Owner direct upload queued with NO PR and NO daily PR cap. "
            "Check GitHub Actions for the sanitized public files."
        )
        return result["actions_url"]

    run(["gh", "auth", "setup-git"], env=env)
    fork = _fork_if_needed(login, env)
    contribution_id = secrets.token_hex(10)
    branch = f"community-{contribution_id}"
    progress(f"Preparing a data-only pull request from {fork}...")
    with tempfile.TemporaryDirectory(prefix="openfishtest-submit-") as directory:
        clone = Path(directory) / "OpenFishtest"
        run(["git", "clone", "--depth", "1", "--branch", "main",
             GIT_URL, str(clone)], env=env)
        run(["git", "-C", str(clone), "checkout", "-b", branch], env=env)
        destination = clone / "submissions" / contribution_id
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "games.pgn").write_bytes(report.pgn)
        (destination / "openings.epd").write_bytes(report.epd)
        run(["git", "-C", str(clone), "add", "--force",
             f"submissions/{contribution_id}/games.pgn",
             f"submissions/{contribution_id}/openings.epd"], env=env)
        run(["git", "-C", str(clone),
             "-c", f"user.name={login}",
             "-c", "user.email=openfishtest-contributor@users.noreply.github.com",
             "commit", "-m", f"data: submit PGN and EPD {contribution_id}"], env=env)
        run(["git", "-C", str(clone), "push", "-u",
             f"https://github.com/{fork}.git", branch], env=env)
        message = (
            "PGN and EPD only. Automatically publish after strict legal game, "
            "color-swapped pair, and EPD opening verification. "
            "This report is not independent proof of engine provenance. "
            "No code, binary or workflow files are proposed."
        )
        progress("Opening the automatically validated GitHub contribution...")
        pr_url = run([
            "gh", "pr", "create", "--repo", TARGET,
            "--base", "main", "--head", f"{login}:{branch}",
            "--title", f"[COMMUNITY PGN/EPD] {contribution_id}",
            "--body", message,
        ], cwd=clone, env=env).splitlines()[-1].strip()
    if not pr_url.startswith(f"https://github.com/{TARGET}/pull/"):
        raise SubmissionError("GitHub did not return an expected pull-request link")
    progress(f"Submitted! Actions will publish the two sanitized files: {pr_url}")
    return pr_url


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Auto-submit local PGN + EPD via GitHub (no admin approval)"
    )
    parser.add_argument("--pgn", type=Path, required=True)
    parser.add_argument("--epd", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.validate_only:
            report = validate_files(args.pgn, args.epd)
            print(
                f"Legal paired PGN+EPD: {report.games} games, "
                f"{report.wins}W/{report.draws}D/{report.losses}L"
            )
            return 0
        print(submit(args.pgn, args.epd))
        return 0
    except (InvalidCommunitySubmission, SubmissionError, OSError) as exc:
        print(f"Submission failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

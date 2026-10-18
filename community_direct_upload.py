"""Owner-authorized, PR-free publication of existing PGN + EPD via GitHub.

Triggered by a push of a new 'community-upload/<24 hex>' branch, usually
created in one browser action from OpenFishtest/upload.html. GitHub Pages
itself never stores files or authenticates a visitor.

SECURITY BOUNDARIES:
- Run only trusted MAIN branch code; never checkout an uploaded branch.
- Restrict actor to the canonical repository owner (not untrusted forks).
- Source commit must have exactly one parent and add exactly two allowed
  data blobs, no other changes or workflow files.
- Fetch immutable Git blobs by SHA via GitHub REST.
- Validate legality, color-swapped paired openings and EPD consistency.
- Publish only canonical sanitized PGN/EPD + generated JSON index.
- Do NOT execute PGN content, UCI engines, external scripts or EXEs.
- Successful re-runs are idempotent and may retry Pages deployment.
- After successful publish the staging branch is removed. A failed run
  leaves the staged branch for GitHub Actions "Re-run jobs".
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys

from community_submission import (
    InvalidCommunitySubmission, check_pr_paths, validate_pair,
    MAX_COMMUNITY_PGN, MAX_COMMUNITY_EPD,
)
from community_publish import GitHub, REPO, DEFAULT_BRANCH, APIError


BRANCH_PATTERN = re.compile(
    r"^refs/heads/community-upload/([0-9a-f]{24})$"
)
HEAD_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
OWNER = "gaong5247-cmd"


def plan_upload(gh: GitHub, event: dict, *, actor: str, repository: str):
    """Return canonical files and metadata based on the immutable source SHA."""
    if repository != REPO:
        raise InvalidCommunitySubmission("Wrong destination repository")
    if actor.casefold() != OWNER.casefold():
        raise InvalidCommunitySubmission(
            "Website direct publish is owner-only; other Contributors use PGN/EPD PRs"
        )
    match = BRANCH_PATTERN.fullmatch(event.get("ref", ""))
    if not match:
        raise InvalidCommunitySubmission("Not an owner upload branch")
    upload_id = match.group(1)
    commit_sha = event.get("after", "")
    if not HEAD_SHA_PATTERN.fullmatch(commit_sha):
        raise InvalidCommunitySubmission("Invalid upload source commit")

    head_ref = gh.get(
        f"repos/{REPO}/git/ref/heads/community-upload/{upload_id}"
    )
    if head_ref.get("object", {}).get("sha") != commit_sha:
        raise InvalidCommunitySubmission(
            "Upload branch was replaced; process only the latest immutable commit"
        )

    commit = gh.get(f"repos/{REPO}/git/commits/{commit_sha}")
    parents = commit.get("parents", [])
    if len(parents) != 1 or not HEAD_SHA_PATTERN.fullmatch(
        parents[0].get("sha", "")
    ):
        raise InvalidCommunitySubmission(
            "Upload commit must have exactly one valid parent"
        )
    parent = parents[0]["sha"]
    comparison = gh.get(f"repos/{REPO}/compare/{parent}...{commit_sha}")
    changes = comparison.get("files")
    if comparison.get("status") != "ahead" or not isinstance(changes, list):
        raise InvalidCommunitySubmission("Could not compare the upload commit")
    if comparison.get("ahead_by") != 1 or comparison.get("total_commits") != 1:
        raise InvalidCommunitySubmission(
            "Upload commit must be one atomic, data-only change"
        )
    if not isinstance(comparison.get("files"), list) or len(changes) != 2:
        raise InvalidCommunitySubmission(
            "Only PGN and EPD data files are accepted, nothing else"
        )
    found_id = check_pr_paths(changes)
    if found_id != upload_id:
        raise InvalidCommunitySubmission("Upload ID mismatch")

    blobs = {}
    for row in changes:
        path = row["filename"]
        suffix = path.rsplit("/", 1)[-1]
        limit = MAX_COMMUNITY_PGN if suffix == "games.pgn" else MAX_COMMUNITY_EPD
        blobs[suffix] = gh.blob_bytes(REPO, row["sha"], limit)
    report = validate_pair(blobs["games.pgn"], blobs["openings.epd"])

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    files = {
        f"docs/data/community/{upload_id}/games.pgn": report.pgn,
        f"docs/data/community/{upload_id}/openings.epd": report.epd,
    }
    entry = report.public_metadata(upload_id, actor, now)
    entry.update({
        "pgn_path": f"docs/data/community/{upload_id}/games.pgn",
        "epd_path": f"docs/data/community/{upload_id}/openings.epd",
        "source_commit": commit_sha,
        "source": "owner_website_direct_upload",
        "manual_upload": True,
    })
    return files, entry


def publish_staged(gh: GitHub, event: dict, actor: str, repository: str):
    files, entry = plan_upload(
        gh, event, actor=actor, repository=repository
    )
    index = gh.index_for_main()
    same_id = next(
        (row for row in index["entries"] if row.get("id") == entry["id"]), None
    )
    same_pgn = next(
        (
            row for row in index["entries"]
            if row.get("pgn_sha256") == entry["pgn_sha256"]
            and row.get("id") != entry["id"]
        ), None
    )
    if same_pgn:
        # A duplicate should NEVER make 100 games look like 200. A
        # repeat upload is acknowledged without appending to public data.
        published_id = same_pgn["id"]
        print(f"Already published identical PGN under {published_id}.")
        already_done = True
    elif same_id:
        if (
            same_id.get("pgn_sha256") != entry["pgn_sha256"]
            or same_id.get("epd_sha256") != entry["epd_sha256"]
        ):
            raise InvalidCommunitySubmission(
                "Upload ID already exists but content hash changed"
            )
        print("Upload already published; re-running Pages deployment only.")
        published_id = entry["id"]
        already_done = True
    else:
        gh.commit_publication(
            files, entry, trusted_owner_upload=True
        )
        published_id = entry["id"]
        already_done = False

    # The canonical PGN/EPD may have been committed during an earlier
    # Actions attempt. An independent Pages dispatch makes this rerunnable.
    gh.deploy_pages()

    # Remove staged RAW PGNs on successful publication. Source commit
    # objects can still be present in GitHub history/caches; do not assume
    # immediate erasure or absolute data privacy.
    try:
        gh.api(
            "DELETE",
            f"repos/{REPO}/git/refs/heads/community-upload/{entry['id']}"
        )
    except APIError as exc:
        print(
            f"::warning::Could not clean up staging branch: {exc}",
            file=sys.stderr
        )
    print(
        f"Publication status: {'already_exists' if already_done else 'new'}; "
        f"entry={published_id}, games={entry['games']}, "
        f"points={entry['points']}/{entry['games']}. "
        "Only legal PGN/EPD consistency was checked; actual engine origin unverified."
    )
    return published_id


def main():
    repo = os.getenv("GITHUB_REPOSITORY", "")
    actor = os.getenv("GITHUB_ACTOR", "")
    if repo != REPO or actor.casefold() != OWNER.casefold():
        raise InvalidCommunitySubmission(
            "Only an authorized OpenFishtest owner push may publish directly"
        )
    import json
    with open(os.environ["GITHUB_EVENT_PATH"], "r", encoding="utf-8") as fh:
        event = json.load(fh)
    gh = GitHub(os.getenv("GITHUB_TOKEN", ""), REPO)
    published_id = publish_staged(gh, event, actor, repo)
    url = (
        "https://gaong5247-cmd.github.io/OpenFishtest/"
        f"data/community/{published_id}/games.pgn"
    )
    print("PUBLIC_PGN_URL: " + url)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(
                "### OpenFishtest — PGN/EPD published\n\n"
                f"- **Submission ID:** {published_id}\n"
                f"- **PGN:** {url}\n"
                "- **No PR, no re-run of chess engines.** "
                "Legal PGN/EPD validated; engine origin unverified.\n"
            )


if __name__ == "__main__":
    try:
        main()
    except InvalidCommunitySubmission as exc:
        print("::error::" + str(exc), file=sys.stderr)
        raise SystemExit(2)

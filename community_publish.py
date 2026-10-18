"""Trusted, data-only GitHub PR auto-publisher for PGN + EPD.

Run in a pull_request_target workflow from the MAIN branch ONLY.
NEVER checkout, import or execute code from the contributor's PR.

Flow:
  fork PR adding submissions/<id>/games.pgn + openings.epd
    -> download exact immutable Git blobs through GitHub REST
    -> validate legal paired PGN and matching EPD (trusted main code)
    -> commit only canonical PGN/EPD plus bounded JSON index into docs/
    -> trigger GitHub Pages workflow_dispatch
    -> close the source PR and comment on the published GitHub Pages links.

Public GitHub PRs are NOT an engine-origin attestation. Nothing from these
submissions is promoted into the official trusted-worker rating list.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from community_submission import (
    InvalidCommunitySubmission, check_pr_paths, validate_pair,
    MAX_COMMUNITY_EPD, MAX_COMMUNITY_PGN,
)

REPO = "gaong5247-cmd/OpenFishtest"
DEFAULT_BRANCH = "main"
INDEX_PATH = "docs/data/community/index.json"
MAX_INDEX_ROWS = 200
MAX_PER_CONTRIBUTOR_DAILY = 3
MAX_COMMUNITY_DAILY = 20


class APIError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"GitHub API HTTP {status}: {message[:220]}")
        self.status = status


class GitHub:
    def __init__(self, token, repo=REPO):
        if not token or len(token) < 10:
            raise RuntimeError("GITHUB_TOKEN missing")
        if repo != REPO:
            raise RuntimeError("Publisher is pinned to the official OpenFishtest repository")
        self.token = token
        self.repo = repo

    def api(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            "https://api.github.com/" + path.lstrip("/"),
            data=data, method=method, headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "OpenFishtest-DataPublisher/1.0",
                **({"Content-Type":"application/json"} if data is not None else {})
            }
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read(8_000_000)
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", "replace")
            raise APIError(exc.code, detail) from exc

    def get(self, path):
        return self.api("GET", path)

    def post(self, path, body):
        return self.api("POST", path, body)

    def patch(self, path, body):
        return self.api("PATCH", path, body)

    def blob_bytes(self, fork, sha, max_size):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", fork):
            raise InvalidCommunitySubmission("Invalid contributor fork identity")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise InvalidCommunitySubmission("Invalid Git blob SHA")
        data = self.get(f"repos/{fork}/git/blobs/{sha}")
        if data.get("encoding") != "base64":
            raise InvalidCommunitySubmission("Contributor file is not a Git base64 blob")
        size = data.get("size")
        if not isinstance(size, int) or size < 0 or size > max_size:
            raise InvalidCommunitySubmission("Contributor file is over the submission limit")
        try:
            payload = base64.b64decode(data.get("content", ""), validate=False)
        except (ValueError, TypeError) as exc:
            raise InvalidCommunitySubmission("Invalid Git blob encoding") from exc
        if len(payload) != size or len(payload) > max_size:
            raise InvalidCommunitySubmission("Git blob size mismatch")
        # Git SHA-1 object ID verification defends against substitutions if
        # the fork pointer is changed while the workflow runs.
        calculated_sha = hashlib.sha1(
            b"blob " + str(len(payload)).encode() + b"\x00" + payload
        ).hexdigest()
        if calculated_sha != sha:
            raise InvalidCommunitySubmission("Git blob SHA-1 integrity check failed")
        return payload

    def write_blob(self, raw):
        payload = {
            "content": base64.b64encode(raw).decode("ascii"),
            "encoding": "base64"
        }
        return self.post(f"repos/{self.repo}/git/blobs", payload)["sha"]

    def index_for_main(self):
        path = quote(INDEX_PATH, safe="/")
        try:
            record = self.get(
                f"repos/{self.repo}/contents/{path}?ref={DEFAULT_BRANCH}"
            )
        except APIError as exc:
            if exc.status == 404:
                return {"version": 1, "entries": []}
            raise
        if record.get("encoding") != "base64":
            raise RuntimeError("Published index has unsupported encoding")
        value = json.loads(base64.b64decode(record["content"]))
        if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
            raise RuntimeError("Published index schema invalid")
        return value

    def verify_no_overwrite(self, entry_id):
        # Reject rewriting a prior publication even when its index entry has
        # aged out of the display list.
        path = f"docs/data/community/{entry_id}/games.pgn"
        try:
            self.get(f"repos/{self.repo}/contents/{path}?ref={DEFAULT_BRANCH}")
        except APIError as exc:
            if exc.status == 404:
                return
            raise
        raise InvalidCommunitySubmission("Submission ID has already been published")

    def current_head(self):
        reference = self.get(f"repos/{self.repo}/git/ref/heads/{DEFAULT_BRANCH}")
        head_sha = reference["object"]["sha"]
        commit = self.get(f"repos/{self.repo}/git/commits/{head_sha}")
        return head_sha, commit["tree"]["sha"]

    def commit_publication(self, files: dict[str, bytes], entry: dict, *, approved_backfill=False, trusted_owner_upload=False):
        blob_shas = {
            path: self.write_blob(data) for path, data in files.items()
        }
        for _ in range(4):
            head_sha, tree_sha = self.current_head()
            self.verify_no_overwrite(entry["id"])
            index = self.index_for_main()
            rows = index["entries"]
            if any(item.get("id") == entry["id"] for item in rows):
                raise InvalidCommunitySubmission("Duplicate published submission")
            now = dt.datetime.now(dt.timezone.utc)
            recent = [
                item for item in rows if _recent(item.get("submitted_at"), now)
            ]
            # Only trusted owner direct-upload Actions may bypass BOTH legacy
            # PR quotas. GitHub API/storage limits still apply. The upload
            # source's untrusted metadata never selects this flag.
            if not (approved_backfill or trusted_owner_upload) and sum(1 for item in recent if item.get("contributor") == entry["contributor"]) >= MAX_PER_CONTRIBUTOR_DAILY:
                raise InvalidCommunitySubmission("Contributor daily limit: 3 valid submissions")
            if not trusted_owner_upload and len(recent) >= MAX_COMMUNITY_DAILY:
                raise InvalidCommunitySubmission("Community daily limit: 20 valid submissions")
            index_bytes = json.dumps({
                "version": 1,
                "updated_at": now.isoformat(timespec="seconds"),
                "entries": [entry] + rows[:MAX_INDEX_ROWS - 1]
            }, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            blob_shas[INDEX_PATH] = self.write_blob(index_bytes)
            tree = self.post(f"repos/{self.repo}/git/trees", {
                "base_tree": tree_sha,
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "sha": sha}
                    for path, sha in blob_shas.items()
                ]
            })
            commit = self.post(f"repos/{self.repo}/git/commits", {
                "message": f"data(community): auto-publish verified PGN/EPD {entry['id']}",
                "tree": tree["sha"], "parents": [head_sha],
            })
            try:
                self.patch(f"repos/{self.repo}/git/refs/heads/{DEFAULT_BRANCH}", {
                    "sha": commit["sha"], "force": False
                })
                return commit["sha"]
            except APIError as exc:
                if exc.status not in (409, 422):
                    raise
                time.sleep(1)
        raise RuntimeError("Main branch changed repeatedly; retry PR publication")

    def deploy_pages(self):
        # GITHUB_TOKEN writes don't trigger on:push workflows. Explicit
        # workflow_dispatch works with the same token (actions:write).
        return self.post(
            f"repos/{self.repo}/actions/workflows/pages.yml/dispatches",
            {"ref": DEFAULT_BRANCH}
        )

    def close_accepted_pr(self, number, entry_id):
        public_url = (
            "https://gaong5247-cmd.github.io/OpenFishtest/"
            f"data/community/{entry_id}/"
        )
        text = (
            "✅ **Automatically accepted.** PGN + EPD were checked for legal chess "
            "moves, reversed colors and the matching opening positions. "
            "**The engine's identity or claimed strength is not independently verified.**\n\n"
            f"- [Download canonical PGN]({public_url}games.pgn)\n"
            f"- [Download canonical EPD]({public_url}openings.epd)\n"
            "- [Community submission index]"
            "(https://gaong5247-cmd.github.io/OpenFishtest/#community)\n\n"
            "These files were published as community data only; official "
            "engine rankings and trusted-worker scores were not modified."
        )
        self.post(f"repos/{self.repo}/issues/{int(number)}/comments", {
            "body": text
        })
        self.patch(f"repos/{self.repo}/pulls/{int(number)}", {"state": "closed"})


def _recent(value, now):
    try:
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return now - dt.timedelta(days=1) <= value <= now
    except (ValueError, TypeError, AttributeError):
        return False


def _validate_event(event, repo=REPO, *, merged_head=None):
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        raise InvalidCommunitySubmission("No pull request event in payload")
    accepted_state = pr.get("state") == "open" if merged_head is None else (
        pr.get("state") == "closed" and pr.get("merged") is True
        and pr.get("head", {}).get("sha") == merged_head
    )
    if not accepted_state or pr.get("draft"):
        raise InvalidCommunitySubmission("The submitted PR is closed or a draft")
    if pr.get("base", {}).get("ref") != DEFAULT_BRANCH or pr.get("base", {}).get("repo", {}).get("full_name") != repo:
        raise InvalidCommunitySubmission("Target branch/repository mismatch")
    fork = pr.get("head", {}).get("repo")
    if not fork or not isinstance(fork.get("full_name"), str):
        raise InvalidCommunitySubmission("Contributor fork unavailable")
    if not re.fullmatch(r"[0-9a-f]{40}", pr.get("head", {}).get("sha", "")):
        raise InvalidCommunitySubmission("Invalid PR head SHA")
    number = pr.get("number")
    if not isinstance(number, int) or number < 1:
        raise InvalidCommunitySubmission("Invalid PR number")
    author = pr.get("user", {}).get("login", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", author):
        raise InvalidCommunitySubmission("Cannot identify contributor GitHub login")
    return pr


def publication_plan(gh, event, *, merged_head=None):
    """Read only exact immutable Git blobs, never PR checkout or scripts."""
    pr = _validate_event(event, merged_head=merged_head)
    number = pr["number"]
    fresh = gh.get(f"repos/{gh.repo}/pulls/{number}")
    if fresh.get("head", {}).get("sha") != pr["head"]["sha"] or (merged_head is None and fresh.get("state") != "open"):
        raise InvalidCommunitySubmission("PR changed during validation; wait for its newest event")
    if merged_head is not None:
        _validate_event({"pull_request": fresh}, merged_head=merged_head)
    if fresh.get("changed_files") != 2:
        raise InvalidCommunitySubmission("Exactly two PGN/EPD changes are required")
    changes = gh.get(f"repos/{gh.repo}/pulls/{number}/files?per_page=100")
    submission_id = check_pr_paths(changes)
    blobs = {}
    for item in changes:
        path = item["filename"]
        if merged_head is not None:
            record = gh.get(f"repos/{pr['head']['repo']['full_name']}/contents/{quote(path, safe='/')}?ref={merged_head}")
            if record.get("type") != "file" or record.get("sha") != item["sha"]:
                raise InvalidCommunitySubmission("PR file does not match the approved immutable head")
        limit = MAX_COMMUNITY_PGN if path.endswith(".pgn") else MAX_COMMUNITY_EPD
        blobs[path.rsplit("/", 1)[1]] = gh.blob_bytes(
            pr["head"]["repo"]["full_name"], item["sha"], limit
        )
    report = validate_pair(blobs["games.pgn"], blobs["openings.epd"])
    files = {
        f"docs/data/community/{submission_id}/games.pgn": report.pgn,
        f"docs/data/community/{submission_id}/openings.epd": report.epd,
    }
    entry = report.public_metadata(
        submission_id, pr["user"]["login"],
        dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    )
    entry["pgn_path"] = files.keys().__iter__().__next__()
    entry["epd_path"] = f"docs/data/community/{submission_id}/openings.epd"
    entry["source_pr"] = number
    if merged_head is not None:
        _validate_event({"pull_request": gh.get(f"repos/{gh.repo}/pulls/{number}")}, merged_head=merged_head)
    return files, entry


def main():
    repo = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    if repo != REPO:
        raise RuntimeError("Auto-publisher must only run in the canonical main repository")
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    gh = GitHub(token, repo)
    files, entry = publication_plan(gh, event)
    gh.commit_publication(files, entry)
    try:
        gh.deploy_pages()
    except APIError as exc:
        # Validated files were committed. Report Pages activation failure
        # without accepting untrusted PR changes or dropping the results.
        print(f"WARNING: Pages workflow dispatch failed: {exc}", file=sys.stderr)
    gh.close_accepted_pr(event["pull_request"]["number"], entry["id"])
    print(
        f"Automatically published {entry['games']} verified-legal games "
        f"and {entry['book_positions']} EPD positions from {entry['contributor']} "
        f"to https://gaong5247-cmd.github.io/OpenFishtest/#community"
    )


if __name__ == "__main__":
    try:
        main()
    except InvalidCommunitySubmission as exc:
        print(f"::error::{str(exc)}", file=sys.stderr)
        raise SystemExit(2)

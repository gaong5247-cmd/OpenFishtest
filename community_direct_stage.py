"""PR-free owner upload using an existing GitHub CLI credential.

This local program uses the owner's existing gh auth login. It does not
print or save the token. Only canonical PGN+EPD are staged on a data-only
community-upload branch. The trusted GitHub Action validates and publishes
the records, then deletes the temporary branch on successful publication.

External Contributors without write access continue to use normal PRs.
"""
import re
import secrets

from community_submission import validate_pair
from community_publish import GitHub, REPO

OWNER = "gaong5247-cmd"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def stage_owner_upload(token: str, pgn: bytes, epd: bytes,
                       *, uploader: str = OWNER, progress=print):
    if uploader.lower() != OWNER.lower():
        raise PermissionError(
            "Only the OpenFishtest repository owner may upload directly"
        )
    report = validate_pair(pgn, epd)
    gh = GitHub(token, REPO)
    user = gh.get("user")
    if (user.get("login") or "").casefold() != OWNER.casefold():
        raise PermissionError("GitHub auth token does not belong to the owner")

    upload_id = secrets.token_hex(12)
    branch = "community-upload/" + upload_id
    prefix = "submissions/" + upload_id + "/"
    progress(f"Staging existing PGN/EPD #{upload_id}; no PR required")
    base_sha, base_tree = gh.current_head()
    if not SHA40.fullmatch(base_sha) or not SHA40.fullmatch(base_tree):
        raise RuntimeError("Invalid main SHA or tree")

    pgn_blob = gh.write_blob(report.pgn)
    epd_blob = gh.write_blob(report.epd)
    new_tree = gh.post(f"repos/{REPO}/git/trees", {
        "base_tree": base_tree,
        "tree": [
            {"path":prefix+"games.pgn", "mode":"100644", "type":"blob", "sha":pgn_blob},
            {"path":prefix+"openings.epd", "mode":"100644", "type":"blob", "sha":epd_blob},
        ],
    })
    if not SHA40.fullmatch(new_tree.get("sha", "")):
        raise RuntimeError("Invalid staged tree")
    new_commit = gh.post(f"repos/{REPO}/git/commits", {
        "message":f"data(owner-upload): stage validated PGN and EPD {upload_id}",
        "tree":new_tree["sha"], "parents":[base_sha],
    })
    if not SHA40.fullmatch(new_commit.get("sha", "")):
        raise RuntimeError("Invalid staged commit")
    gh.post(f"repos/{REPO}/git/refs", {
        "ref":"refs/heads/"+branch, "sha":new_commit["sha"]
    })
    progress(
        f"GitHub data upload accepted: {report.games} games, "
        f"{report.wins}W/{report.draws}D/{report.losses}L. "
        "GitHub Actions will validate and publish."
    )
    return {
        "id":upload_id,
        "upload_branch":branch,
        "actions_url":
            f"https://github.com/{REPO}/actions/workflows/community-direct-upload.yml",
        "published_url":
            "https://gaong5247-cmd.github.io/OpenFishtest/"
            f"data/community/{upload_id}/games.pgn",
        "games":report.games,
        "points":report.wins + report.draws / 2,
        "status":"queued_for_verification",
    }

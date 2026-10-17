"""Publish sanitized local public results to GitHub Pages without a public API.

Uses existing GitHub CLI authentication to update docs/data/status.json.
The script makes no repository changes when the public data is unchanged.
You can schedule it on the self-hosted Windows machine (e.g. every 30 min).
"""
import base64
import json
import subprocess
import sys

DEFAULT_REPO = "gaong5247-cmd/OpenFishtest"
PAGES_PATH = "docs/data/status.json"


def gh_api(*args, body=None):
    cmd = ["gh", "api", *args]
    result = subprocess.run(
        cmd, input=json.dumps(body) if body is not None else None,
        text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "gh api failed")
    return json.loads(result.stdout)


def publish(repo=DEFAULT_REPO):
    # Import server code only on the trusted PC, never in GitHub Pages.
    from server import snapshot
    public = snapshot()
    if any(word in json.dumps(public).lower() for word in (
        "admin_token", "worker_token", "lease_id", "worker_id"
    )):
        raise RuntimeError("Sensitive data accidentally included in snapshot")
    endpoint = f"repos/{repo}/contents/{PAGES_PATH}"
    existing = gh_api(endpoint, "-H", "Accept: application/vnd.github+json")
    existing_sha = existing["sha"]
    # A static export should not claim to be live even if worker backend is online.
    public["published_via"] = "github-pages-snapshot"
    # Avoid unnecessary GitHub commits every time a scheduler checks for updates.
    # The timestamp is only refreshed if underlying data has actually changed.
    try:
        previous = json.loads(base64.b64decode(existing["content"]).decode("utf-8"))
        # Deep-copy before removing comparison-only fields; keep storage bytes
        # in the actual published JSON.
        new_data = json.loads(json.dumps(public))
        old_data = json.loads(json.dumps(previous))
        new_data.pop("updated_at", None)
        old_data.pop("updated_at", None)
        # DB/WAL byte usage fluctuates during read and is not a substantive result.
        new_data.get("storage", {}).pop("used_bytes", None)
        old_data.get("storage", {}).pop("used_bytes", None)
        if new_data == old_data:
            print("Public snapshot unchanged; no GitHub commit needed.")
            return False
    except (KeyError, ValueError, TypeError, UnicodeDecodeError):
        pass
    encoded = json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True)
    payload = {
        "message": "data: publish public OpenFishtest results snapshot",
        "branch": "main",
        "sha": existing_sha,
        "content": base64.b64encode((encoded + "\n").encode()).decode()
    }
    gh_api("-X", "PUT", endpoint, "--input", "-", body=payload)
    print(f"Published public snapshot to {repo}:{PAGES_PATH}")
    return True


if __name__ == "__main__":
    try:
        publish(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Snapshot publish failed: {exc}", file=sys.stderr)
        sys.exit(1)

"""Safe localhost-only uploader for OpenFishtest's static upload page.

GitHub Pages cannot read local gh auth credentials or accept PGN POSTs.
A local web server serves the same page, accepts only PGN+EPD, and reuses
the user's existing GitHub CLI login.

- Owner: data-only community-upload branch, PR-free trusted Actions publisher.
- Other Contributors: existing vetted PGN+EPD-only fork PR publisher.

The browser NEVER receives a GitHub auth token. The server does not execute
EXEs, does not retain uploaded files, and does not alter local PGN results.
Local bridge only: do not expose it through a tunnel or port forwarding.

Security: loopback-only bind, exact Host/Origin, no CORS, custom header,
bounded JSON, legal paired PGN/EPD validation and one upload at a time.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from community_submission import (
    InvalidCommunitySubmission, MAX_COMMUNITY_EPD, MAX_COMMUNITY_PGN,
    validate_pair,
)
from contributor_submit import SubmissionError, submit
from community_direct_stage import stage_owner_upload

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
OWNER = "gaong5247-cmd"
# Base64 cost ~ceil(raw_bytes/3)*4 plus minimal JSON.
MAX_REQUEST_BYTES = 4 * ((MAX_COMMUNITY_PGN + 2) // 3) + \
    4 * ((MAX_COMMUNITY_EPD + 2) // 3) + 8 * 1024
DOCS = Path(__file__).resolve().parent / "docs"
USER_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
ASSETS = {
    "/": ("upload.html", "text/html; charset=utf-8"),
    "/upload.html": ("upload.html", "text/html; charset=utf-8"),
    "/upload.js": ("upload.js", "text/javascript; charset=utf-8"),
    "/upload.css": ("upload.css", "text/css; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def github_login():
    """Read only username, not credential."""
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    login = proc.stdout.strip()
    if proc.returncode or not USER_PATTERN.fullmatch(login):
        return None
    return login


def github_token():
    """Return OAuth token to Python process only; never expose to browser."""
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SubmissionError("GitHub CLI authentication unavailable") from exc
    if proc.returncode or len(proc.stdout.strip()) < 10:
        raise SubmissionError("Sign into your GitHub account: gh auth login")
    return proc.stdout.strip()


def submit_bytes(pgn: bytes, epd: bytes, *, username: str | None = None):
    """Use one canonical validator, then select route by gh login role."""
    report = validate_pair(pgn, epd)
    username = username or github_login()
    if not username:
        raise SubmissionError("Sign into your own GitHub account: gh auth login")
    if username.casefold() == OWNER.casefold():
        result = stage_owner_upload(
            github_token(), report.pgn, report.epd,
            uploader=username, progress=lambda _message: None,
        )
        return {
            "role": "owner",
            "method": "direct",
            "status": "queued_for_actions",
            "upload_id": result["id"],
            "url": result["actions_url"],
            "games": report.games,
            "points": report.wins + report.draws / 2,
            "note": "No PR; GitHub Actions will still validate/publish.",
        }
    with tempfile.TemporaryDirectory(prefix="openfishtest-upload-") as folder:
        directory = Path(folder)
        pgn_path = directory / "games.pgn"
        epd_path = directory / "openings.epd"
        pgn_path.write_bytes(report.pgn)
        epd_path.write_bytes(report.epd)
        pr_url = submit(
            pgn_path, epd_path, progress=lambda _message: None,
        )
    return {
        "role": "contributor",
        "method": "pull_request",
        "status": "queued_for_actions",
        "url": pr_url,
        "games": report.games,
        "points": report.wins + report.draws / 2,
        "note": "Data-only PR; automatic checks and daily quota apply.",
    }


class LocalUploadHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler_class, *, docs=DOCS):
        super().__init__(address, handler_class)
        self.docs = Path(docs).resolve()
        self.upload_lock = threading.Lock()


class LocalUploadHandler(BaseHTTPRequestHandler):
    server_version = "OpenFishtestLocalUpload/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Do not log arbitrary request paths, headers or user data.
        pass

    def _allow_host(self):
        return self.headers.get("Host", "") == (
            f"{HOST}:{self.server.server_port}"
        )

    def _json(self, code, body):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _check_host(self):
        if not self._allow_host():
            self._json(403, {"error": "Untrusted Host; local access only"})
            return False
        return True

    def do_GET(self):
        if not self._check_host():
            return
        url = urlsplit(self.path)
        if url.query or url.fragment:
            self._json(404, {"error": "Unknown path"})
            return
        if url.path == "/api/status":
            username = github_login()
            role = (
                "owner" if username and username.casefold() == OWNER.casefold()
                else "contributor" if username else None
            )
            self._json(200, {
                "authenticated": username is not None,
                "username": username,
                "role": role,
                "endpoint": "local_only",
                "token_required_in_browser": False,
                "requires_pr": role == "contributor",
            })
            return
        found = ASSETS.get(url.path)
        if not found:
            self._json(404, {"error": "Unknown local asset"})
            return
        filename, content_type = found
        path = (self.server.docs / filename).resolve()
        if not path.is_relative_to(self.server.docs) or not path.is_file():
            self._json(404, {"error": "File unavailable"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'; object-src 'none'"
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self._json(403, {"error": "Cross-origin requests are forbidden"})

    def do_POST(self):
        if not self._check_host():
            return
        if self.path != "/api/upload":
            self._json(404, {"error": "Unknown upload endpoint"})
            return
        origin = f"http://{HOST}:{self.server.server_port}"
        if (
            self.headers.get("Origin") != origin
            or self.headers.get("X-OpenFishtest-Local") != "1"
            or self.headers.get("Content-Type", "").split(";")[0].strip()
                != "application/json"
            or self.headers.get("Sec-Fetch-Site", "same-origin")
                not in ("same-origin", "none")
        ):
            self._json(403, {"error": "Use the local upload page on this PC"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except (ValueError, TypeError):
            self._json(411, {"error": "Content-Length required"})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(413, {"error": "PGN/EPD upload size exceeded"})
            return
        if not self.server.upload_lock.acquire(blocking=False):
            self._json(429, {"error": "One upload at a time"})
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                self._json(400, {"error": "Incomplete upload request"})
                return
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict) or set(payload) != {
                    "pgn_base64", "epd_base64"
                }:
                    raise ValueError("Unexpected fields")
                pgn = base64.b64decode(payload["pgn_base64"], validate=True)
                epd = base64.b64decode(payload["epd_base64"], validate=True)
                if not 0 < len(pgn) <= MAX_COMMUNITY_PGN:
                    raise ValueError("PGN above 2MB")
                if not 0 < len(epd) <= MAX_COMMUNITY_EPD:
                    raise ValueError("EPD above 512KiB")
            except (ValueError, KeyError, TypeError, binascii.Error):
                self._json(422, {"error": "Only PGN and EPD base64 are supported"})
                return

            try:
                validate_pair(pgn, epd)
            except InvalidCommunitySubmission as exc:
                self._json(422, {"error": str(exc)[:270]})
                return
            try:
                result = submit_bytes(pgn, epd)
            except (SubmissionError, InvalidCommunitySubmission,
                    PermissionError, RuntimeError, OSError):
                # Never echo private GH credentials in diagnostics.
                self._json(502, {"error":
                    "GitHub submission failed. Original PGN/EPD remain on PC. "
                    "Check gh auth login and GitHub Actions."})
                return
            self._json(202, result)
        finally:
            self.server.upload_lock.release()


def serve(*, port=DEFAULT_PORT, open_browser=True, docs=DOCS):
    with LocalUploadHTTPServer(
        (HOST, port), LocalUploadHandler, docs=docs
    ) as server:
        url = f"http://{HOST}:{server.server_port}/upload.html"
        print("OpenFishtest localhost uploader / GitHub CLI auth")
        print("Listening only at: " + url)
        print("GitHub token is never sent to this page.")
        print("Stop with Ctrl+C or close the Contributor application.")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=0.15)
        except KeyboardInterrupt:
            print("Local uploader stopped.")


def main():
    parser = argparse.ArgumentParser(description="Local PGN/EPD uploader")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        serve(open_browser=not args.no_browser)
    except OSError as exc:
        print(
            "Loopback port 8765 unavailable. Another uploader may be running: "
            "http://127.0.0.1:8765/upload.html",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

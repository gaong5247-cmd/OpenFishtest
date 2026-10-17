#!/usr/bin/env python3
"""Trusted UCI handshake probe running INSIDE the rootless arena container.

This is not a security scanner. It only captures bounded id name / id author
and advertised UCI option defaults, with resource/clock limits and no network.
"""
import json
import os
import re
import select
import signal
import subprocess
import sys
import time

LIMIT_BYTES = 24 * 1024
LIMIT_SECONDS = 18


def clean(text, n=120):
    return "".join(c for c in text if c.isprintable() and c not in "<>{}")[:n].strip()


def parse_uci(lines, digest=""):
    name = None
    author = ""
    options = []
    for line in lines:
        if line.startswith("id name "):
            name = clean(line[8:], 80)
        elif line.startswith("id author "):
            author = clean(line[10:], 80)
        elif line.startswith("option name ") and len(options) < 24:
            match = re.match(r"option name (.*?) type (\w+)(?: (.*))?$", line)
            if match:
                option_name = clean(match.group(1), 80)
                option_type = clean(match.group(2), 20)
                tail = match.group(3) or ""
                default = re.search(
                    r"(?:^|\s)default (.*?)(?=\s(?:min|max|var)\s|$)", tail
                )
                if option_name and option_type in (
                    "check", "spin", "combo", "button", "string"
                ):
                    options.append({
                        "name": option_name,
                        "type": option_type,
                        "default": clean(default.group(1), 100) if default else ""
                    })
    if not name:
        raise ValueError("Engine did not return UCI 'id name'")
    # UCI has id name/author/options, but NO guaranteed version field.
    version_match = re.search(r"(?i)(?:v|version\s*)?(\d+\.\d+(?:\.\d+){0,2})", name)
    version = version_match.group(1) if version_match else (
        "build-" + digest[:12] if digest else "unversioned"
    )
    return {
        "name": name, "version": version, "author": author,
        "options": options, "uciok": True
    }


def run_probe():
    proc = subprocess.Popen(
        ["/usr/local/bin/arena-challenger"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True,
        bufsize=0
    )
    lines = []
    total = 0
    line_buffer = bytearray()
    deadline = time.monotonic() + LIMIT_SECONDS
    try:
        proc.stdin.write(b"uci\n")
        proc.stdin.flush()
        uciok = False
        while time.monotonic() < deadline:
            readable, _, _ = select.select(
                [proc.stdout], [], [], min(0.5, max(0, deadline - time.monotonic()))
            )
            if not readable:
                if proc.poll() is not None:
                    break
                continue
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            total += len(chunk)
            if total > LIMIT_BYTES:
                raise ValueError("Engine UCI output exceeded 24KB")
            for byte in chunk:
                if byte in (10, 13):
                    if line_buffer:
                        text = line_buffer.decode("utf-8", "replace").strip()
                        lines.append(text)
                        line_buffer.clear()
                        if text == "uciok":
                            uciok = True
                            break
                else:
                    line_buffer.append(byte)
            if uciok:
                break
        if not uciok:
            raise ValueError("Engine did not reply 'uciok' within 18 seconds")
        return parse_uci(lines)
    finally:
        try:
            if proc.stdin:
                proc.stdin.write(b"quit\n")
                proc.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)


if __name__ == "__main__":
    try:
        result = run_probe()
        # Print exactly ONE bounded JSON object for the trusted runner.
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print("UCI probe rejected engine: " + str(exc)[:120], file=sys.stderr)
        raise SystemExit(2)

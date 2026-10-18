# OpenFishtest PGN + EPD upload: one GitHub login for everyone

The public scoreboard runs on **static GitHub Pages**:
https://gaong5247-cmd.github.io/OpenFishtest/

The public upload info page is:
https://gaong5247-cmd.github.io/OpenFishtest/upload.html

GitHub Pages cannot run Python, access a local GitHub CLI login, store
uploaded PGNs or execute chess engines. The public page explains how to
start a **localhost-only PGN uploader** running on the Contributor's PC.

## First-time setup (all users)

In PowerShell, log into YOUR own GitHub account once:

~~~powershell
gh auth login
~~~

On the Contributor PC, with OpenFishtest cloned:

~~~powershell
git pull origin main
.\Start-Upload.cmd
~~~

Or launch Start-Contributor.cmd and click the existing PGN/EPD upload button.
Either route opens the local upload GUI at:

    http://127.0.0.1:8765/upload.html

Select games.pgn and openings.epd from an existing completed-match folder,
typically %USERPROFILE%\OpenFishtest-Results\match-<id>. No EXE or code is
uploaded. The local Python process reuses GitHub CLI authentication and
never sends its OAuth token to HTML/JavaScript or public Pages.

## Owner and normal Contributor behavior

| User | Upload route | Pull request |
| --- | --- | --- |
| gaong5247-cmd (repo owner) | Data-only GitHub branch, trusted Actions | **No** |
| Any other GitHub user | PGN+EPD-only fork PR, trusted Actions | **Yes** |

Owner direct uploads bypass the custom three-accepted-PRs/day quota.
Other Contributors keep it as an abuse limit. These are application rules,
not a GitHub platform-imposed limit. GitHub API/Actions/storage limits
and account permissions still apply.

On successful GitHub submission, the UI reports **queued**, not already
published. Trusted Actions verifies the legal chess moves, reversed-color
opening pairs and EPD before publication. Community results are labeled
unverified engine origin and do not automatically affect official Elo.

## Automatically after a real Fastchess match

Start-Contributor.cmd has a checkbox to automatically publish PGN/EPD.
With that checkbox enabled:

1. Fastchess runs locally and writes games.pgn, openings.epd and fastchess.log.
2. Python validates the completed PGN/EPD pair.
3. The local GitHub CLI login identifies the user:
   owner => direct data-only Git branch; other users => data-only PR.
4. GitHub Actions checks and publishes; the public Pages index updates.

No administrator token or browser PAT entry is required.

The local PGN/EPD/log files remain in place, even on upload failure.
For old matches or a failed upload, use the website's local upload GUI or:

~~~powershell
.\.venv\Scripts\python.exe contributor_submit.py --pgn "C:\path\games.pgn" --epd "C:\path\openings.epd"
~~~

The same result can be retried without replaying games.

Owner bulk-submit example, using the same gh auth identity:

~~~powershell
.\.venv\Scripts\python.exe contributor_backfill.py --submit --limit 10
~~~

## File limits and privacy

- PGN: at most **2,000,000 bytes**
- Normalized EPD: at most **512 KiB**
- Even-numbered complete matches: **2–200 games**
- Opening positions and reversed engine colors must match
- Original local files are NEVER automatically deleted

The earlier **200 MiB book-input allowance** applies to the optional
separate, self-hosted HTTPS Arena, not to this GitHub community PGN
publishing path. Use the small normalized EPD created by Contributor.

## Local API

Bound to **127.0.0.1:8765**, never 0.0.0.0:

- GET /api/status -> GitHub username, role and authenticated flag; no token.
- POST /api/upload -> JSON PGN/EPD base64 (bounded), same-origin-only,
  with X-OpenFishtest-Local: 1, returning queued status.
- GET /upload.html -> local interface, same visual page as static Pages.
- No CORS wildcard, no execution endpoints, no remote engine transfer.

For automation, use the existing Python contributor_submit.py function with
PGN/EPD paths. It uses the same publication pipeline without opening a tab.

Never port-forward, tunnel or expose this local bridge to remote clients.
It does not replace a security-audited Internet-facing backend.

OpenFishtest is independent from official Stockfish Fishtest. File
validation cannot prove the real engine's identity or certify Elo.

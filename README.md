# OpenFishtest ♞

An independent, free, open-source **UCI chess engine testing prototype**.

**Stockless is the mandatory, version-pinned reference engine** with an arbitrary Elo coordinate of 3000. All other engines are challengers, and their outcomes must be reported honestly.

**Current v0.2 status:** GitHub Pages dashboard, SQLite/FastAPI, Stockless reference registration, trusted local Fastchess worker job queue, leased paired matches, worker-reported PGN result accounting, 5GB data policy, optional GitHub Releases archives, and static snapshot publishing via GitHub CLI.

**Not yet implemented:** an independently audited public volunteer network, sandboxed distribution of engines, cryptographically verified chess moves/results, robust statistical confidence intervals or SPRT, automatic worker installer, and a publicly hosted backend. Worker results are labeled unverified.

## GitHub Pages: free public website

The website is in the docs directory, with a deployment workflow in .github/workflows/pages.yml.

After merging the implementation PR:

1. Go to **Repository → Settings → Pages**.
2. Under **Build and deployment → Source**, select **GitHub Actions**.
3. If needed, run **Actions → Deploy GitHub Pages → Run workflow**.
4. After a successful deployment, the expected URL is:

https://gaong5247-cmd.github.io/OpenFishtest/

**Important:** GitHub Pages can host HTML/CSS/JS, not Python, FastAPI, SQLite, UCI workers or server-side computation. The website initially displays an honest empty offline snapshot from docs/data/status.json.

## Self-hosted backend on Windows

Requires Python 3.10 or later. Run PowerShell in the repository:

~~~powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENFISHTEST_DATA = "$PWD\data"
$env:OPENFISHTEST_ADMIN_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$env:OPENFISHTEST_ADMIN_TOKEN # Save privately; never put it on GitHub.
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
~~~

Use http://127.0.0.1:8000/docs to inspect the REST API. The backend listens on the same PC only, by design. Do not directly expose this prototype API to the world.

To register Stockless, use a new PowerShell window and supply the saved token:

~~~powershell
$headers = @{ "X-Admin-Token" = "YOUR_SECRET_TOKEN" }
Get-FileHash "C:\path\to\Stockless.exe" -Algorithm SHA256

$stockless = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/admin/engines" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ name="Stockless"; version="v0.7"; sha256="PUT_REAL_64_HEX_SHA256_HERE" } | ConvertTo-Json)
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/admin/reference" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ engine_id=$stockless.id } | ConvertTo-Json)
~~~

Register a challenger via the same engine endpoint, then use the following endpoints:

- POST /api/admin/tests: JSON body with engine_id and an even games_target.
- PUT /api/admin/tests/{id}/results: manually replace cumulative wins/draws/losses. **Only enter real observed results.**
- GET /api/public/snapshot: public read-only display data.
- GET /api/health: data usage and reference readiness.

A separately installed trusted worker can now conduct real UCI games via Fastchess. Until that worker submits actual PGNs, the website shows no fabricated test games or engine ranks.

## Live results from github.io

The default docs/config.json contains an empty api_base, so it loads the published static file docs/data/status.json. Use the offline snapshot publisher described below to update results through GitHub Pages **without** making your home server public. For a direct live API (optional):

1. Safely host a **public HTTPS** backend endpoint yourself.
2. Configure CORS to allow https://gaong5247-cmd.github.io.
3. Set api_base in docs/config.json to the backend HTTPS origin (not /api paths).

Never put an admin token in a GitHub Pages file or public JavaScript. GitHub Pages does not proxy requests to your home PC. A visitor's localhost refers to the visitor's own PC.

The API requires additional hardening (HTTPS, reverse proxy, authorization, rate limits, network restrictions, auditing) before public deployment. Static status snapshots can be published without a live backend, but are not real-time.


## 2A. Install your own Fastchess worker (real UCI games)

OpenFishtest **does not download or execute random GitHub EXEs**. Download [Fastchess](https://github.com/Disservin/fastchess/releases) yourself, and place your trusted Stockless and challenger UCI engines on your computer. Put NNUE files in the engine's working directory as required by that engine.

Copy worker-config.example.json to a **private** worker-config.json and edit:
- fastchess: full path to your fastchess.exe.
- engines: each entry maps a **real SHA-256 digest** to its **local executable path**. Both Stockless and the challenger must be explicitly listed.
- books: optionally map a trusted EPD/PGN book SHA-256 to its local file path.
- concurrency: start with 1; increase only after checking CPU thermals and stability.

Find file hashes with PowerShell:

~~~powershell
Get-FileHash "C:\Engines\Stockless.exe" -Algorithm SHA256
Get-FileHash "C:\Engines\Challenger.exe" -Algorithm SHA256
Get-FileHash "C:\Books\openings.epd" -Algorithm SHA256
~~~

Save **two separate secrets** in the PowerShell session that starts the local server. The worker secret can be copied to your own worker machine but must never be put in GitHub Pages:

~~~powershell
$env:OPENFISHTEST_ADMIN_TOKEN = "PUT_A_RANDOM_ADMIN_SECRET_HERE"
$env:OPENFISHTEST_WORKER_TOKEN = "PUT_A_DIFFERENT_RANDOM_WORKER_SECRET_HERE"
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
~~~

In a separate PowerShell window, use the worker secret:

~~~powershell
$env:OPENFISHTEST_WORKER_TOKEN = "THE_SAME_WORKER_SECRET"
.\.venv\Scripts\python.exe worker.py --config worker-config.json --server http://127.0.0.1:8000 --once
# To keep processing future tests, omit --once:
.\.venv\Scripts\python.exe worker.py --config worker-config.json --server http://127.0.0.1:8000
~~~

The server must have an approved Stockless engine registered and pinned as reference. You must also register the challenger, and create a test:

~~~powershell
$adminHeaders = @{ "X-Admin-Token" = $env:OPENFISHTEST_ADMIN_TOKEN }
# Replace the ID with your approved challenger ID.
$testSpec = @{ engine_id = 2; games_target = 100; batch_games = 20; tc = "10+0.1" }
# For varied chess openings add a real book_sha256 (64 hex chars) and book_format = "epd".
Invoke-RestMethod http://127.0.0.1:8000/api/admin/tests -Method Post -Headers $adminHeaders -ContentType application/json -Body ($testSpec | ConvertTo-Json)
~~~

The API assigns 20 games per batch by default. Fastchess plays color-reversed 2-game pairs. The worker sends a PGN after each batch, which is saved by the server in data/pgn/test-ID. The server checks PGN metadata and W/D/L but **does not prove the moves were legal or that the remote machine honestly executed the engines**. Results remain explicitly marked as worker-reported / unverified.

Lease heartbeats renew an active job every 30 seconds; after disconnection the server can give the job to a different authorized worker. Retrying a completed report will not double-count scores. After 3 failures a test is paused with worker_error status.

**Important security boundary:** the default HTTP endpoint binds to 127.0.0.1. For a different machine, configure a properly authenticated TLS reverse proxy before allowing it to connect; the worker refuses insecure non-loopback HTTP. This is still an MVP, not a public volunteer computing service.


Test operations (authenticated admin only):

- POST /api/admin/tests/{id}/pause: revoke active leases, keep remaining work.
- POST /api/admin/tests/{id}/resume: resume paused or worker_error tests.
- POST /api/admin/tests/{id}/cancel: permanently stop a queued/running/paused test.

## 2B. Show actual results on github.io without opening a public port

When the self-hosted server has real results and your PC is authenticated to GitHub via gh auth login, run:

~~~powershell
.\.venv\Scripts\python.exe publish_snapshot.py
~~~

The publisher reads **only** public fields from the local server database and pushes a static read-only JSON snapshot to docs/data/status.json in the repository. The GitHub Pages workflow republishes the site automatically. The web dashboard clearly says *Published snapshot*, not real time.

You can run publish_snapshot.py from **Windows Task Scheduler** every 30–60 minutes. To register both maintenance tasks for the local Windows account, after installing GitHub CLI and running gh auth login:

~~~powershell
.\scripts\Install-ScheduledMaintenance.ps1 -PublishMinutes 30 -ArchiveTime "03:00"
~~~

This schedules a 30-minute public Pages snapshot and a verified GitHub Releases PGN archive every day at 03:00. The wrappers default to the clone's data directory; if you configured OPENFISHTEST_DATA elsewhere, update the wrapper environment first so both processes use the same data. Creating scheduled tasks may require permission on your Windows account. **Review these scripts before enabling them.** Scheduled tasks only run while the relevant PC/user has access to the local files and gh credentials. These do not provide off-site backup.

To suspend them:

~~~powershell
schtasks /Change /TN "OpenFishtest-Publish" /DISABLE
schtasks /Change /TN "OpenFishtest-Archive" /DISABLE
~~~

To remove them, use schtasks /Delete with /TN and /F.

The archive job requires GitHub CLI access, is not an unlimited storage service, and deletes original PGNs only after a verified Release upload.


## PGN retention and storage

Only the data directory is included in the **5,000,000,000 byte data budget**. Your Windows installation, Python environment, other software, and binaries are outside this directory and outside the quota.

| Policy | Value | Implementation |
| --- | ---: | --- |
| PGN retention | 7 days | Old files become eligible for archive |
| Archive trigger | 3.0 GB | Files over 5 minutes old become eligible |
| Pause new test registration | 4.25 GB | API returns HTTP 507 |
| Data target | 5.0 GB | Soft policy, not filesystem-enforced maximum |
| Archive format | daily .tar.zst | Zstandard level 3, small multi-PGN bundles |
| Archive destination | GitHub Releases | Date tags pgn-archive-YYYY-MM-DD |

The archive command processes worker-completed PGN files under data/pgn. It does not run automatically until you schedule the CLI on the self-hosted machine.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-archive.txt
# Install GitHub CLI and sign in with: gh auth login
.\.venv\Scripts\python.exe archive.py         # Dry run, no deletion
.\.venv\Scripts\python.exe archive.py --apply # Upload and verify
~~~

After upload, the CLI checks the remote asset SHA-256 and byte size and deletes only local PGN files that have not changed. Failed uploads do not delete the PGNs. Optionally run this script once per day via Windows Task Scheduler after manual testing. GitHub Releases is not an unlimited archive or sole backup.

## Development

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
~~~

Roadmap: independent move-level verification, hardened public volunteer authentication and sandboxing, distributed opening-book management, trusted job scheduling, SPRT, ratings with confidence intervals, and optional public HTTPS API access.

Security: do not execute unknown uploaded engine executables on volunteers' computers. SHA-256 metadata alone does not prove an engine binary is safe.

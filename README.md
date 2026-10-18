# OpenFishtest ♞

An independent, free, open-source **UCI chess engine testing prototype**.

**Stockless is the mandatory, version-pinned reference engine** with an arbitrary Elo coordinate of 3000. All other engines are challengers, and their outcomes must be reported honestly.

**Current v0.2 status:** GitHub Pages dashboard, SQLite/FastAPI, Stockless reference registration, trusted local Fastchess worker job queue, leased paired matches, worker-reported PGN result accounting, 5GB data policy, optional GitHub Releases archives, and static snapshot publishing via GitHub CLI.

**Not yet implemented:** an independently audited public volunteer network, sandboxed execution of arbitrary new engines, cryptographically attested engine execution, official Fishtest GSPRT, automatic one-click worker installation, or a publicly hosted private backend. Actual worker results remain labeled unverified.

## v0.3 community release — what is usable today?

| Feature | Implemented | Operational caveat |
| --- | --- | --- |
| Actual test standings | Yes | **Empty until real approved-worker PGNs are submitted**; do not invent games |
| Global volunteer enrollment | Admin-issued individual revocable tokens | A globally reachable **HTTPS API + sandboxing/rate limits** is still required before launching a public fleet |
| Website engine registration requests | Browser form opens a pre-filled GitHub Issue | Maintainer manually approves engine builds and SHA-256 before execution |
| Website test requests | Browser form opens a pre-filled GitHub Issue | Queueing games requires a maintainer approval and available CPU |
| Recorded game board + PGN download | Yes, last 8 genuine locally available games | Completed PGNs are published in the static snapshot, not live move-by-move streaming |
| Elo intervals + SPRT | Yes, **approximate/experimental** | Wilson fractional-draw approximation for small/unpaired results; paired normal approximation and Gaussian SPRT are NOT official Fishtest GSPRT |
| Worker contribution rankings | Yes, public aliases and completed job/game counts | Still worker-reported, not attested CPU computation |
| Korean + English | Yes | Switch language on the public page |
| Local admin controls | Yes | Visit **http://127.0.0.1:8000/admin** on the backend PC |

### Start the local management interface

Set a strong and **private** administrator token and start the FastAPI server as described below. Open:

**http://127.0.0.1:8000/admin**

This gives you browser forms to register known SHA-256 engine builds, pin Stockless as reference, queue an even-numbered match, approve a volunteer worker, revoke its token, and pause/resume/cancel tests. It never downloads a binary or silently starts a match. All actual chess games are run by trusted local workers.

### Public participants: register engines / request tests / apply as a worker

Visit **https://gaong5247-cmd.github.io/OpenFishtest/#contribute**. Fill out one of the three web forms. The website opens a *pre-filled GitHub Issue* that the participant checks and submits while logged into GitHub. Nothing goes directly to the private home API and no administrator secret is placed on GitHub Pages. Approval is **manual** in this release.

After approval, the administrator opens the local admin page and registers an exact engine build or an individual worker identity. When enrolling a volunteer, the one-time **worker token is shown only once**. Send it only to the approved volunteer through a private channel; never paste it into an Issue or website.

Approved volunteers set their local OPENFISHTEST_WORKER_TOKEN environment variable, map the exact approved SHA-256 executables into their private worker-config.json, and launch the trusted worker with **--worker-id <the approved worker ID>**. The admin may instead keep the whole fleet on one trusted PC. A real external volunteer needs a **properly secured HTTPS endpoint**; github.io only displays results, and the local demo still has no public backend. Do not enable the legacy shared OPENFISHTEST_WORKER_TOKEN on a public service.

### Real PGN playback and statistics

Worker PGNs are parsed with **python-chess** to reject illegal moves, count two-game reversed-color pairs, and build board FEN timelines. The browser can replay the last 8 *actual* recorded games, step by step, and download a small PGN; archived historical PGNs belong in GitHub Releases. The browser cannot independently prove who ran the engine or that non-mate results correspond to authentic resignations. The UI labels these as **worker-reported / unverified**.

Published Elo differences are relative to **Stockless = 3000** only; they are not comparable to FIDE, CCRL, CEDR, or an across-hardware/TC rating pool. The 95% interval shown is an **approximation** (Wilson pseudo-Bernoulli score when no full pairs exist; Gaussian paired-score CI when sufficient data exist). The displayed sequential likelihood ratio compares Elo0=0 vs Elo1=5 with a **Gaussian pair model**; this is a **research prototype**, not the validated GSPRT implementation used in official Fishtest. See [official Fishtest statistics documentation](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html).

All PGNs originate from actual submissions. No fake matches, ratings or worker contribution records are seeded.

---

## Opening books up to 200 MiB (v0.5.1)

Drag **EPD or PGN** opening books up to **200 MiB (209,715,200 bytes)** into the
[automatic challenger arena](https://gaong5247-cmd.github.io/OpenFishtest/#arena).
The 128 MiB limit for EXE/ZIP chess engines stays unchanged.

- The browser streams the book to FastAPI; **no 200 MiB Python bytearray** is created.
- The uploaded original is temporary and deleted after parsing, even on error.
- At most **500 distinct legal opening positions** from a bounded input prefix
  are kept as a small, SHA-256-pinned EPD. Fastchess takes 50 of those positions
  for its 100 color-reversed games. The full 200 MiB is **not** tested verbatim.
- Only the first 10,000 records are considered; PGN parsing additionally has a
  24 MiB / 128 KiB-per-line safety budget. Books with pathological leading
  records may fail despite being under the file-size cap.
- The 5 GB server-data target stays in effect. One large upload at a time and
  a 3-attempt daily upload limit per source help avoid storage exhaustion.
- The HTTPS Caddy example has **separate 201 MiB book / 129 MiB engine**
  request limits. Both the API and the website also enforce their own limits.

This functionality only becomes externally available after the owner configures
and enables a real HTTPS API, a pinned Stockless reference and an isolated arena VM.

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

The API assigns 20 games per batch by default. Fastchess uses explicit `-games 2 -rounds N -repeat` for color-reversed 2-game pairs. The worker sends a PGN after each batch, which is saved by the server in data/pgn/test-ID. The server checks PGN metadata and W/D/L but **does not prove the moves were legal or that the remote machine honestly executed the engines**. Results remain explicitly marked as worker-reported / unverified.

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

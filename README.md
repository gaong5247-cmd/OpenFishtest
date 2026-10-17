# OpenFishtest ♞

An independent, free, open-source **UCI chess engine testing prototype**.

**Stockless is the mandatory, version-pinned reference engine** with an arbitrary Elo coordinate of 3000. All other engines are challengers, and their outcomes must be reported honestly.

**Current MVP status:** Static website, SQLite/FastAPI API, Stockless reference registration, engine registry, test records, manually entered cumulative results, 5GB data monitoring, and optional GitHub Releases PGN archiving CLI.

**Not yet implemented:** actual UCI/Fastchess match execution, volunteer workers, secured user submissions, opening pairs, automatic PGN ingestion, verified Elo or SPRT, and a publicly hosted backend. Do not present manual results as independently verified match outcomes.

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

The app cannot conduct chess games yet, so the website does not display fabricated test games or engine ranks.

## Live results from github.io

The default docs/config.json contains an empty api_base, so it loads the committed static file docs/data/status.json and shows **Static preview**. For actual live results:

1. Safely host a **public HTTPS** backend endpoint yourself.
2. Configure CORS to allow https://gaong5247-cmd.github.io.
3. Set api_base in docs/config.json to the backend HTTPS origin (not /api paths).

Never put an admin token in a GitHub Pages file or public JavaScript. GitHub Pages does not proxy requests to your home PC. A visitor's localhost refers to the visitor's own PC.

The API requires additional hardening (HTTPS, reverse proxy, authorization, rate limits, network restrictions, auditing) before public deployment. Static status snapshots can be published without a live backend, but are not real-time.

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

The archive command only processes completed PGN files under data/pgn. It is **not connected to an engine worker yet**.

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

Roadmap: approved UCI/Fastchess workers, trusted builds and sandboxing, paired openings, result verification, PGN ingestion, job queue and scheduling, SPRT, robust ratings with confidence intervals, and external HTTPS read-only API access.

Security: do not execute unknown uploaded engine executables on volunteers' computers. SHA-256 metadata alone does not prove an engine binary is safe.

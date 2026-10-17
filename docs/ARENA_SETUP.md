# OpenFishtest Arena — self-hosted deployment (v0.5 preview)

## Two-file, no-manual-UCI workflow

The public [OpenFishtest website](https://gaong5247-cmd.github.io/OpenFishtest/#arena)
accepts an engine file and, optionally, an opening-book file:

1. **Drop an engine**: Windows x86_64 **.exe** directly, or a ZIP with a
   root-level Linux x86_64 executable named **engine** and optionally up to
   five flat .nnue files. No name, version, SHA-256, or UCI option entry.
2. **Drop an opening book**: .epd or .pgn (optional when the operator has
   configured a default .epd). The API validates at least **50 distinct legal
   opening positions**; PGNs are converted to canonical EPD.
3. Click **Start 100-game Arena**. The server calculates the binary and
   normalized book SHA-256 automatically and queues the candidate.
4. A *separate disposable Linux VM* runs a rootless container with
   Fastchess. The VM starts a **bounded UCI handshake** and saves its
   advertised \`id name\`, \`id author\` and up to 24 UCI options.
5. After 100 real color-reversed games, **wins + 0.5 draws >= 55** qualifies
   the candidate for a private operator download/release decision. Under 55
   causes the uploaded executable to be deleted; the public PGN/statistics
   remain available.

A Windows .exe can run only when the operator explicitly configures the
dedicated rootless **Wine** arena image. It may fail due to missing DLLs,
CPU features or Wine compatibility. This is not equivalent to native
Windows execution and is NOT a guarantee every UCI EXE works.

**No uploaded executable runs in the GitHub Pages browser, FastAPI HTTP
server or volunteers' PCs.** Wine itself is NOT sandboxing; the security
boundaries are the separate VM, rootless containers, blocked networking,
read-only engine volumes, quotas and operator oversight.

## Why the website can say "Backend unavailable"

GitHub Pages is static. A working public upload requires:

- A computer/VM that remains on, with a real network connection
- A public DNS name and HTTPS certificates, e.g. through Caddy
- A running OpenFishtest FastAPI service on 127.0.0.1:8000
- A separate disposable Linux x86_64 VM with rootless Docker for untrusted
  challenger execution
- A trusted, hash-pinned Linux Stockless reference **ELF** and NNUE resources
- A trusted Linux Fastchess binary and a minimum 50-position EPD book
  (uploaded books may replace that default for a particular test)
- A privately managed shared data volume between the test service and VM

The code does not purchase a hostname, provide a public IP, launch a cloud
VM, or run the server autonomously. Do NOT expose FastAPI admin endpoints
directly. Use an HTTPS reverse proxy with explicit route allowlists. See
[deployment/Caddyfile.example](../deployment/Caddyfile.example).

## Build the two trusted runner images

On the dedicated VM install rootless Docker and verify the daemon shows
the \`rootless\` security option. Use the *official* Fastchess source and
build instructions:
https://github.com/Disservin/fastchess

Provide your trusted Linux x86_64 Fastchess executable at
\`deployment/fastchess\` (never commit it or an untrusted uploaded binary).

From the repository root:

~~~bash
docker build -f deployment/Dockerfile.arena \
  -t openfishtest/arena:0.4 deployment

docker build -f deployment/Dockerfile.arena-wine \
  -t openfishtest/arena-wine:0.5 deployment
~~~

The second image includes Debian Wine and the **trusted**
\`arena-challenger\` launcher, plus \`uci_probe.py\`. Run untrusted
binaries ONLY in the disposable VM, not on the web/database host.

## Pin the real Stockless reference

Your first arena must pin a Stockless build so that \`Stockless = 3000\`
is a reproducible relative rating anchor.

- Download the official Stockless v0.7 **Linux x86_64 AVX2** release from
  https://github.com/gaong5247-cmd/Stockless/releases/tag/Stockless_v0.7
- Inspect and unpack it into a private, trusted reference directory.
  Place its trusted Linux ELF at \`/private/stockless/engine\`, with any
  required NNUE resources next to the executable.
- Run \`sha256sum /private/stockless/engine\`.
- At **http://127.0.0.1:8000/admin** on the local backend machine:
  register an approved Stockless build with the **ELF's own SHA-256**,
  select it, and press **Pin reference**. You can also use the documented
  local-only admin API. Do **not** use the release ZIP's SHA as the ELF hash.
- Set \`OPENFISHTEST_ARENA_REFERENCE_DIR=/private/stockless\` in the VM
  service environment (path visible from the VM).

The ordinary Windows **Pin-Stockless.ps1** script is useful for testing
Windows UCI workers, but its Windows SHA is **not** interchangeable with
the Linux ELF SHA pinned for the Linux VM arena.

## Operator environment

Illustrative settings (adjust actual secure paths and credentials):

~~~bash
export OPENFISHTEST_DATA=/srv/openfishtest/data
export OPENFISHTEST_ADMIN_TOKEN='your_own_strong_secret'
export OPENFISHTEST_ARENA_REFERENCE_DIR=/private/stockless
export OPENFISHTEST_ARENA_BOOK=/private/books/openings.epd
export OPENFISHTEST_ARENA_IMAGE=openfishtest/arena:0.4
export OPENFISHTEST_ARENA_WINDOWS_IMAGE=openfishtest/arena-wine:0.5
# Only after security and container setup have been reviewed:
export OPENFISHTEST_ARENA_UPLOADS=1
export OPENFISHTEST_WINDOWS_ARENA=1
~~~

First run FastAPI on localhost, then run the isolated VM process:

~~~bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000
# On the isolated disposable Linux VM:
python arena_runner.py
~~~

For operator-controlled file-sharing and VM mount topology, use
read-only engine and book mounts inside each rootless container. The
runner must be able to access its required files; do not mount unrelated
host directories or any Docker socket inside containers.

## Browser frontend

Set \`docs/config.json\` to your real HTTPS API origin:

~~~json
{"api_base": "https://api.your-real-domain.example"}
~~~

Replace that example with an actual domain. Never put a secret in this
public JSON. Then publish the GitHub Pages dashboard normally.

The default configuration intentionally leaves the API origin **blank**
and disables uploads until a real server has been configured.

## Automatic daily archiving (5GB policy)

PGNs can be archived with the existing \`archive.py --apply\` CLI after
\`gh auth login\`. A Windows script is included to register 30-minute
public result snapshots and a **daily** archive task at 03:00. This
automation runs only while the self-hosted Windows machine and necessary
credentials are available. For Linux, use systemd timers or a local cron
job after reviewing the same script.

- 7-day PGN retention target
- 3.0GB archive pressure trigger
- 4.25GB stop assigning new jobs
- 5GB soft budget (not a filesystem quota)
- SHA-256 verified GitHub Releases upload before local PGN deletion

This archive is not an unlimited backup service. Back up SQLite separately.

## Statistical and security limitations

A 55/100 score is a **selection threshold**, not proof of a statistically
significant improvement. The existing approximate Elo interval / Gaussian
SPRT is experimental and is **not Stockfish Fishtest GSPRT**. Chess PGNs
can be legal yet still lack independent engine-identity attestation.

Unknown executable files can be malicious. Rootless Docker, Wine and
UCI validation do not guarantee complete isolation; public operation
requires a separate VM, strict resource and network controls, operator
monitoring and additional audits before accepting untrusted uploads.

No actual Stockless vs challenger game has been verified as completed by
this documentation or by CI. Only a separately configured real engine
run can demonstrate successful live execution.

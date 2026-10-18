# Contributing to OpenFishtest

Thanks for helping build a fair, global community for UCI chess-engine testing.

OpenFishtest **always uses a pinned Stockless build as the reference**, but **never assumes Stockless wins**. Results are published with their limitations.

## Participate without commands

Visit: https://gaong5247-cmd.github.io/OpenFishtest/#contribute

Use the website to submit one of three requests:

1. **Engine registration** — UCI engine name, version, public source/release link.
2. **Test request** — challenger version, even game count, time control and purpose.
3. **CPU volunteer** — public alias, operating system and optional non-sensitive CPU info.

The forms open a prefilled GitHub Issue. A maintainer reviews each request. The preview does not accept arbitrary unreviewed executable uploads, silently create test jobs or automatically distribute engine binaries.

## Volunteer worker protocol

A maintainer issues a **unique revocable worker ID and secret** through the local admin console. Keep secrets private. Inspect and approve the engine binaries and Fastchess executable yourself. Configure their exact paths and SHA-256 values in your private worker-config.json.

Detailed setup is in the README. The worker requires a backend on the same machine or a securely operated **HTTPS** endpoint. **GitHub Pages cannot host the worker API.**

Only run computations you explicitly consent to, and stop your worker whenever needed. Contributed game counts shown on the website are not externally attested.

## Reproducibility

Engine comparisons should record:
- Stockless reference version + SHA-256 and challenger version + SHA-256
- Hardware architecture, threads, Hash and nondefault UCI options
- Time control and adjudication settings
- Opening book hash and matched two-game white/black pairs
- Exact PGN, game totals and test date

The website displays **actual submitted games only**, never invented demonstrations. Elo confidence intervals and exploratory SPRT results are not equivalent to official Stockfish Fishtest GSPRT.

## Developer workflow

Open an Issue, work on a dedicated branch, add tests, and submit a pull request to main. CI runs Python API/worker tests, Node checks and EN/KO translation coverage. Avoid committing large PGNs or engine binaries directly to Git history.

Respect the licenses and attribution of the chess engines and opening books you contribute.

## Administrator recovery of merged community data

If a PGN/EPD PR was merged before publication, a repository administrator can
use Actions → **Administrator community backfill** → **Run workflow**, selecting
`main`. Enter the source PR number, its exact 40-character **head SHA** (not the
merge commit), and a public approval reason. This is an explicit approval of a
single historical submission, including an exception to the contributor's
3-publications-per-day limit. Ordinary PR submission quotas are unchanged;
the community-wide 20-publications-per-day limit still applies to backfills.

The original dispatcher and any rerun actor must both have repository `admin`
permission. The workflow rejects forks, non-main execution, drafts, unmerged
closed PRs, changed heads, wrong target branches/repositories, and any change
other than the two new submission files. It reuses the existing blob size/SHA-1,
legal move, reversed-color pair and EPD validation. No contributor code is
checked out or executed, and no games are run.

Approval actor, reason, immutable head SHA, run URL and attempt are recorded in
the published index. Existing submission IDs are rejected, including publications
no longer present in the bounded index; repeated runs never overwrite data or
count games twice. Backfill and automatic publication share a concurrency group
and use non-forced main updates. Branch protection remains authoritative: if a
write is refused, do not bypass protection or grant additional permissions.

After success, check the Pages deployment and public index/download hashes. If
publication succeeded but Pages dispatch/deployment failed, rerun **Deploy GitHub
Pages** on main; do not republish the submission. The recovery workflow uses the
existing `GITHUB_TOKEN` with only `contents: write` and `actions: write`, a subset
of the automatic publisher's permissions. If administrator verification is denied
by the API, stop and resolve access with the repository owner rather than weakening
the check. Engine identity remains unverified.

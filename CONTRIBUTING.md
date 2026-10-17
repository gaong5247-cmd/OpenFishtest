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

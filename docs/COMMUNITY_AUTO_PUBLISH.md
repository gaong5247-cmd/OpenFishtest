# Serverless, review-free community PGN+EPD publication

### What happens automatically

1. The Contributor selects **their own trusted local** Fastchess, Stockless,
   challenger UCI executable and EPD/PGN opening book in the Windows GUI.
2. They explicitly consent to execute those local binaries and click
   **CPU 기여 시작 · 자동 대국**. The program recommends how many simultaneous
   games their CPU can handle, runs real color-reversed Fastchess matches,
   validates the legal moves and checks that every opening pair matches the
   book, and writes **games.pgn** plus **openings.epd**.
3. With the auto-publish checkbox enabled (the default), the program
   creates a data-only PR via their **own GitHub identity**.
4. A trusted GitHub Actions workflow validates only the two immutable
   PGN/EPD Git blobs, strips PGN comments/untrusted metadata, and atomically
   commits canonical files + a bounded public index into **docs/data/community**.
   It then invokes GitHub Pages deployment and closes the data PR.
5. The **Community PGN/EPD** section on github.io displays the links.
   No administrator approves a PR, no central always-on PC or HTTPS API is
   necessary, and the Contributor NEVER needs the ADMIN or worker token.

**This requires GitHub and GitHub Actions.** It is not an infrastructure-free
peer-to-peer system. GitHub Pages serves results but does not conduct games.

### For Contributor PCs (Windows)

Install Python 3.10+, Git for Windows, [GitHub CLI](https://cli.github.com/),
and [Fastchess](https://github.com/Disservin/fastchess/releases) once.
Contributors authenticate **their own account**, once:

    gh auth login

Download/extract a trusted Stockless reference engine and challenger EXE.
Do NOT auto-download or execute anonymous engine uploads. Both are selected
by the volunteer, who may start/stop CPU use freely.

Download/clone this repo on their PC. Double-click:

    Start-Contributor.cmd

In the UI choose the files, set concurrency (one game normally runs two
single-thread UCI engines), then click **CPU 기여 시작 · 자동 대국**.

Alternatively submit *existing* legal paired matches:

    python contributor_submit.py --pgn real-games.pgn --epd openings.epd

A GitHub login is required. PGN and EPD are the ONLY files committed in each
contributor's source PR. The original source PR is closed after trusted
validation; it is **not merged**, and no contributor scripts can run on the
privileged publication runner.

### Limitations

- This GitHub-only PR route accepts **PGN <= 2,000,000 bytes** and
  **EPD <= 512 KiB** per submission, **2–200 even-numbered games**.
  These are small, public data contributions, not a 200 MiB opening-book
  distribution system. The existing **200 MiB EPD/PGN drag-drop** feature
  belongs to the optional self-hosted HTTPS arena backend and is separate.
- The Windows contributor GUI can locally *open and normalize a 200 MiB book*,
  but publishes only its bounded, normalized EPD opening positions.
- The GitHub workflow uses **pull_request_target** with a trusted main-branch
  checkout. It NEVER checks out untrusted PR code. It checks that the entire
  PR consists of exactly two immutable, new files in a designated folder,
  downloads them by blob SHA through the GitHub API, validates chess rules
  and matched EPD openings, and creates ONLY canonical PGN+EPD and index JSON.
- This high-privilege automation needs the repository's GitHub Actions
  write permissions and permission to publish to main. A maintainer should
  review any changes to the trusted scripts/workflow. GitHub may require
  Actions approval according to its organization/fork policy.
- Canonical PGNs have comments, annotations, arbitrary headers and alternate
  variations stripped. This prevents embedding arbitrary instructions in
  published metadata but does NOT prove a Contributor actually ran the claimed
  chess engine.
- Automatic community results are **never placed in official Elo/SPRT rating
  lists**, because a public fork can submit fabricated but legal games.
- A maximum of **3 accepted submissions per Contributor per 24h** and **20
  accepted community submissions globally per 24h** are published. These are
  not DoS-proof; GitHub has separate API and Actions usage limits.
- GitHub Pages files are retained in Git history and should not be used as
  an unlimited backup. Historical PGN archive/retention needs a separate policy.
- The repo's existing private-worker / isolated-VM arena continues separately.
  Anonymous executables are NOT transferred to Contributors by this workflow.

### Administration

After installing the new workflow on main, verify the repository's
**Settings → Actions → General** permits GitHub Actions to create commits
through its scoped GITHUB_TOKEN, and that branch protection permits the
automatic publisher. This automation explicitly requests contents:write,
pull-requests:write, issues:write, and actions:write (for Pages dispatch).

See the workflow in .github/workflows/community-auto-publish.yml and the
pure validator in community_submission.py.

This action is intentionally low-trust on *engine identity* but high-trust on
*file type and PGN/EPD format*. Treat the public community leaderboard as
community-submitted research data, not certified benchmark results.

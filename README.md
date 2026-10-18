# ♞ OpenFishtest

**One-click community chess engine testing, powered by Contributors' own CPUs.**

OpenFishtest is a free, independent project with a GitHub Pages scoreboard.
Choose trusted local Stockless and challenger UCI engines, run Fastchess,
and automatically publish the resulting **PGN + EPD** through GitHub Actions.

- **Public results:** https://gaong5247-cmd.github.io/OpenFishtest/#community
- **Score:** points = wins + 0.5 × draws
- **Normalized score:** score percent = 100 × points / completed games
- **No public HTTPS backend, admin token, or remote EXE upload** for contributors
- Original PGN, EPD and logs remain on each Contributor's PC

> OpenFishtest validates legal chess moves and matching color-reversed
> opening pairs, but does NOT cryptographically attest which engine actually
> played them. Community results are **unverified origin** data, not a
> certified engine ranking.

## NEW: GitHub login once, upload PGN/EPD with no browser token

The [public upload page](https://gaong5247-cmd.github.io/OpenFishtest/upload.html)
is static, so it cannot itself read your PC's GitHub login or save files.

For **manual uploads**, run the matching local upload interface:

~~~powershell
git pull origin main
.\Start-Upload.cmd
~~~

It opens **http://127.0.0.1:8765/upload.html**. Choose your existing
games.pgn and openings.epd, then click PGN/EPD 자동 게시 시작.

Every user signs in once with **gh auth login** using their OWN GitHub
identity. Neither the admin nor regular Contributors paste access tokens
into a public web page:

- **Repository owner:** the local API creates a trusted, data-only GitHub
  branch. GitHub Actions validates it and publishes without a new PR.
  The legacy 3-accepted-PRs-per-day application restriction is avoided.
- **Regular Contributor:** the SAME local website automatically creates
  a strictly PGN+EPD-only fork PR. Actions validates and auto-publishes
  it under the existing community contribution quota.

The normal **Start-Contributor.cmd** game application calls exactly these
same role-specific GitHub routines automatically at the end of each
successful Fastchess match when auto-submit is checked. You do NOT have
to visit/upload manually after each game. This is a queued upload, and
the site updates only AFTER the trusted Actions/Pages run succeeds.

You can also submit **old or failed-to-upload PGNs** from Start-Upload.cmd,
contributor_submit.py, or contributor_backfill.py without playing again.
Original local PGN/EPD/log files are kept on failure and success.

See [upload setup and localhost API](docs/UPLOAD_GUIDE.md). The local helper
binds ONLY 127.0.0.1:8765 and must never be forwarded to the Internet.
The public site is still static; GitHub is the shared publication host.

---

## Windows: start contributing

Install Python 3.10+, Git for Windows, [GitHub CLI](https://cli.github.com/)
and [Fastchess](https://github.com/Disservin/fastchess/releases) once.

Authenticate your own GitHub account:

~~~powershell
gh auth login
~~~

Clone and install the project:

~~~powershell
git clone https://github.com/gaong5247-cmd/OpenFishtest.git
cd OpenFishtest
py -3 -m pip install -r requirements.txt
~~~

For an existing clone, use **git pull origin main** (not git push)
to update it. Then double-click **Start-Contributor.cmd**, or run:

~~~powershell
.\Start-Contributor.cmd
~~~

Choose your **own trusted** Fastchess executable, Stockless reference UCI
engine, challenger UCI engine and EPD/PGN opening book. Set the CPU concurrent
game count; click **CPU 기여 시작 · 자동 대국**. The programs run locally.

After a completed match, the app checks PGN/EPD, chooses the owner direct
upload or the regular Contributor data-only PR using the GitHub CLI account,
and GitHub Actions automatically publishes sanitized PGN+EPD.
No administrator approval is required for valid community data.
Neither untrusted PR code nor EXEs are executed by GitHub Actions.

### Results stay on your PC

~~~text
%USERPROFILE%\OpenFishtest-Results\match-<random-id>\
  games.pgn
  openings.epd
  fastchess.log
~~~

Original files are NOT deleted after submission. The GitHub publication
route permits up to **2,000,000 bytes PGN**, **512 KiB normalized EPD**,
**2–200 even-numbered games**, **3 accepted PRs per Contributor per day**
and **20 accepted community PRs per day**.

The input opening book can be up to 200 MiB but only a bounded subset of
up to 500 distinct legal positions is normalized into the small public EPD.
The original large book is not committed to Git.

## Score conversion: 100, 200, or any match length

A win is one point, a draw is half a point, and a loss is zero.

**Points = W + D / 2**

**Score percent = 100 × Points / (W + D + L)**

Examples from real public records:

| Games | W | D | L | Points | Score percent |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 200 | 25 | 73 | 102 | 61.5 / 200 | **30.75%** |
| 200 | 60 | 59 | 81 | 89.5 / 200 | **44.75%** |
| 200 | 59 | 67 | 74 | 92.5 / 200 | **46.25%** |

**A 55% comparison means 55 points out of 100 games, 110 points out of
200, or 11 points out of 20. It is NOT a fixed 55 raw-point cutoff.**

The website's estimated Elo difference is a provisional score-to-logistic
conversion: ΔElo = 400 × log10(p / (1 − p)), where p = points/games.
This is **not official Fishtest GSPRT**, an independent engine audit or
a certified Elo ranking. Paired 95% intervals are normal approximations.
The 55% line is only a screening guide, not an automatic Release verdict.

Records come from GitHub's public data index and are not seeded with
fictitious chess results. Avoid mixing ratings from different time controls,
engine builds, books and hardware into one supposedly official Elo.

## Re-submit old PGN matches without replaying

Preview previously saved games:

~~~powershell
.\.venv\Scripts\python.exe contributor_backfill.py
~~~

Create up to three new, validated data-only PRs in a rolling 24-hour period:

~~~powershell
.\.venv\Scripts\python.exe contributor_backfill.py --submit
~~~

Submission URLs and PGN hashes are stored in the local
.community-submissions.json ledger. Invalid or incomplete games are skipped,
not fabricated or deleted.

See the [full GitHub-only Contributor guide](docs/COMMUNITY_AUTO_PUBLISH.md).

## Advanced / legacy features

The optional [FastAPI and isolated Linux VM arena](docs/ARENA_SETUP.md)
remains available to experienced operators but **is not needed for the
main public one-click workflow**. Also see [AI data connectors](docs/AI_CONNECT.md),
[security notes](SECURITY.md), [privacy](docs/privacy.html), and
[contribution guide](CONTRIBUTING.md).

Never run arbitrary uploaded EXEs on volunteers' computers. The 5GB local
storage policy applies to the optional self-hosted backend, not GitHub's
public-storage quota. OpenFishtest is independent of official Stockfish
Fishtest; respect engine and opening-book licenses.

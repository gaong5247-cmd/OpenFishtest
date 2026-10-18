# Community contributions: PGN + EPD only

Contributor PRs do NOT merge executable code, and are not used to modify
the official Stockless ranking. The trusted GitHub Actions publisher accepts
a PR only when it ADDS exactly these two files:

    submissions/<new-random-12-to-40-lowercase-hex-id>/games.pgn
    submissions/<same-id>/openings.epd

The PGN must use canonical Fastchess engine names **Challenger** and
**Stockless**, color-swapped two-game opening pairs, and actual legal moves.
The EPD must match the starting positions, in order. Partial games may use
a contiguous subset of a larger EPD opening book.

No executable, ZIP, script, workflow, arbitrary JSON metadata or Git LFS
pointer is allowed. Maximum sizes: PGN 2,000,000 bytes; EPD 512 KiB;
up to 200 games per submission.

A trusted GitHub Actions workflow validates each PR and writes sanitized
PGN + EPD under docs/data/community. The source PR is CLOSED without merging.
The GitHub Pages website is refreshed automatically; no owner approval.

Contributors only need their own GitHub account and GitHub CLI once; never
provide an OpenFishtest admin token or a global worker secret.

A legal PGN does **not** prove the claimed engine actually played it.
Community entries are labeled unverified and never alter official engine
rankings or certified SPRT scores.

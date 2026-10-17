# OpenFishtest security policy

OpenFishtest v0.3 is an **early preview**, not a security-audited public worker platform.

## Supported configuration

- **GitHub Pages** hosts only public static HTML/CSS/JS and a published JSON snapshot. Never put administrator or worker tokens in this repository, Pages config, logs, Issues or Releases.
- **FastAPI / SQLite** should run on localhost or an operator-controlled private network. Do **not** expose the development API directly to the public internet.
- A remote worker deployment needs a trusted HTTPS reverse proxy, secure token transport, authentication, audit logs, rate limits, anti-spam controls and resource isolation before volunteers can connect.
- Each approved volunteer should have an individual revocable token. The legacy shared worker secret is only for local migration and should **not** be used for a public fleet.
- The Python worker only launches explicitly operator-approved local paths whose SHA-256 matches the registered build. A hash match is not an antivirus scan or proof of safe code. Unknown engine executables still require sandboxing, resource limits and human review.
- The PGN protocol checks legal chess moves and reversed-color opening pairs. This is **not** proof that the participant really ran the claimed engine or obtained a truthful result.
- Displayed Elo intervals and SPRT are approximate research implementations; do not use them to allocate prizes or certify rankings.

## Report a vulnerability

Prefer a **private GitHub security advisory** through the repository Security tab (if enabled). Do not post access tokens, server addresses or exploit secrets in public GitHub Issues.

If you suspect impersonation or token leakage, revoke the worker in the local administrator panel and rotate affected credentials. Disable a public service until it has been reviewed.

## Backups and storage

The local data directory is intentionally ignored by Git. Keep independent backups of the SQLite database and important PGNs. GitHub Releases are a public archival facility, **not an unlimited free backup service**. The 5GB policy is a **soft budget**, not a filesystem quota.

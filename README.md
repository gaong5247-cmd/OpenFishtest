# OpenFishtest MVP

Self-hosted UCI engine test registry. **Stockless is the mandatory reference engine**.

## Run on Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:OPENFISHTEST_ADMIN_TOKEN = "CHANGE_TO_A_LONG_RANDOM_SECRET"
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs.

## Implemented

- SQLite-backed engine/test registry
- Versioned, SHA-256-identified approved UCI engines
- Stockless mandatory reference engine
- Even game counts for future paired openings
- Aggregate W/D/L result recording
- Storage usage report and admission guard at 4.25GB, within a 5GB data budget
- Admin-token-protected writes

## Planned, not implemented yet

This is **not yet a distributed Fishtest replacement**. No actual worker matching, Fastchess execution, PGN uploads, GitHub Releases archival, Elo/SPRT or automatic cleanup is implemented. The archive trigger of 3GB is a policy marker, not an active uploader.

**Security:** do not expose the development API directly to the public internet. Never commit tokens or download and execute untrusted engine binaries on volunteer PCs. GitHub Releases must not be the sole backup.

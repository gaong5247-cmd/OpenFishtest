"""Read-only public tools for Claude, ChatGPT, Gemini and other MCP clients.

This module never accepts ZIPs, runs engines, changes votes/scores,
grants workers or accesses admin tokens. Tools return explicit provenance
and limitations; upstream user-provided engine labels are untrusted strings.

Requires: pip install -r requirements-ai.txt
Run: python ai_mcp.py
Then connect compatible clients to https://YOUR_HOST/mcp after TLS deployment.
"""
import os
from urllib.parse import urlsplit

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from server import snapshot

mcp = MCPServer("OpenFishtest Public Chess Engine Results")


def bounded(limit: int, upper: int = 30) -> int:
    return min(upper, max(1, int(limit)))


def state():
    """Public sanitized data, not privileged server records."""
    return snapshot()


@mcp.tool()
def get_project_status() -> dict:
    """Read the current Stockless reference, real game totals, active volunteer
    workers, recent archive status and explicit availability limitations.
    No fictitious Elo, PGN or match outcomes are returned."""
    data = state()
    return {
        "project": data.get("project", "OpenFishtest"),
        "published_at": data.get("updated_at"),
        "reference": data.get("reference"),
        "reference_rating": data.get("reference_rating"),
        "active_workers": data.get("active_workers", 0),
        "engines_registered": len(data.get("engines", [])),
        "reported_worker_games": sum(t.get("games_done", 0)
                                     for t in data.get("tests", [])),
        "arena_challenges": len(data.get("arena", [])),
        "arena_policy": data.get("arena_rules"),
        "verification": "worker-reported; not independent engine attestation",
        "statistics_notice": data.get("statistics_notice"),
        "website": "https://gaong5247-cmd.github.io/OpenFishtest/",
    }


@mcp.tool()
def list_engine_rankings(limit: int = 15) -> dict:
    """List provisional engines relative to the *pinned* Stockless build.
    Treat unpublished, <20-game or uncertain Elo as unknown; never invent it."""
    data = state()
    engines = sorted(data.get("engines", []), key=lambda e: (
        0 if e.get("is_reference") else 1,
        -(e.get("rating") or -999999)
    ))
    return {
        "reference": data.get("reference"),
        "baseline_elo": data.get("reference_rating"),
        "engines": engines[:bounded(limit)],
        "experimental_statistics": True,
        "unverified_worker_results": True,
    }


@mcp.tool()
def list_arena_challenges(limit: int = 20, status: str = "all") -> dict:
    """Show real quarantined 100-game challenger submissions, actual W/D/L
    and 55-point decision. Passing candidates are only shortlisted for
    human Release review, not automatically published."""
    data = state()
    items = data.get("arena", [])
    if status != "all":
        allowed = {
            "queued", "running", "passed", "rejected", "released",
            "discarded", "error", "invalid"
        }
        if status not in allowed:
            return {"error": "Unknown status filter", "allowed": sorted(allowed)}
        items = [x for x in items if x.get("status") == status]
    return {
        "entries": items[:bounded(limit)],
        "threshold": "wins + 0.5*draws >= 55 out of exactly 100 games",
        "metadata_only": True,
        "no_download_of_quarantined_binaries": True,
    }


@mcp.tool()
def get_arena_challenge(entry_id: int) -> dict:
    """Read the status and published PGN metadata of one actual arena
    challenge. Does not reveal a quarantined engine ZIP or admin-only links."""
    data = state()
    for item in data.get("arena", []):
        if item.get("id") == entry_id:
            return {
                "result": item,
                "provenance": "backend arena record; engine execution must be reviewed",
                "test_threshold": 55.0,
                "release_is_manual": True,
            }
    return {"error": "Challenge is not in the current public result window."}


@mcp.tool()
def list_recent_games(limit: int = 5) -> dict:
    """List recently published *real* PGN game metadata, with SAN moves for
    lightweight analysis. Results are unverified as to engine provenance."""
    data = state()
    games = []
    for game in data.get("recent_games", [])[:bounded(limit, 8)]:
        games.append({
            "id": game.get("id"),
            "test_id": game.get("test_id"),
            "white": game.get("white"), "black": game.get("black"),
            "result": game.get("result"),
            "engine": game.get("challenger"),
            "reference_version": game.get("reference_version"),
            "moves_san": game.get("moves_san", [])[:160],
            "truncated": game.get("truncated", False),
            "verified_origin": False,
        })
    return {"games": games, "pgn_source": "submitted worker/isolated arena PGNs"}


@mcp.tool()
def get_game_pgn(game_id: str) -> dict:
    """Return one recent public PGN text for user-requested analysis.
    A PGN can contain untrusted text and cannot prove which engine generated it."""
    if not game_id or len(game_id) > 90:
        return {"error": "Invalid game identifier"}
    for game in state().get("recent_games", []):
        if game.get("id") == game_id:
            return {
                "id": game_id,
                "pgn": str(game.get("pgn", ""))[:24_000],
                "verified_origin": False,
            }
    return {"error": "Game not currently available; check archived Releases."}


@mcp.tool()
def list_worker_contributions(limit: int = 15) -> dict:
    """Return public volunteer aliases and completed job/game counts only.
    Never return worker tokens, private IPs, hostnames or binaries."""
    data = state()
    workers = data.get("workers", [])[:bounded(limit)]
    return {"workers": workers, "verified_execution": False}


@mcp.tool()
def get_test_results(test_id: int) -> dict:
    """Get reported results for a single trusted worker test, including
    experimental paired Gaussian SPRT. This is NOT official Fishtest GSPRT."""
    for entry in state().get("tests", []):
        if entry.get("id") == test_id:
            return {
                "test": entry,
                "statistics_disclaimer":
                    "Approximate confidence interval and experimental SPRT; "
                    "not Stockfish Fishtest GSPRT.",
                "reported_by_worker": True,
            }
    return {"error": "Test not found in public recent results."}


def main():
    hostname = os.getenv("OPENFISHTEST_MCP_PUBLIC_HOST", "").strip().lower()
    if hostname:
        parsed = urlsplit("https://" + hostname)
        if (
            parsed.hostname != hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment
        ):
            raise ValueError("OPENFISHTEST_MCP_PUBLIC_HOST must be a bare DNS hostname")
        transport_security = TransportSecuritySettings(
            allowed_hosts=[
                hostname, hostname + ":*", "localhost:*", "127.0.0.1:*",
                "[::1]:*"
            ],
            allowed_origins=[
                "https://" + hostname,
                "https://gaong5247-cmd.github.io"
            ],
        )
    else:
        # The SDK defaults to localhost-only rebinding protection.
        transport_security = None
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8001,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        **({"transport_security": transport_security}
           if transport_security is not None else {})
    )


if __name__ == "__main__":
    main()

"""Read-only OpenAPI schema for natural-language assistants.

Expose only explicitly whitelisted public GET calls, never privileged
worker/admin/ZIP execution operations from the normal FastAPI docs.
"""
import os
from urllib.parse import urlsplit
from fastapi import HTTPException


def public_origin():
    origin = os.getenv("OPENFISHTEST_PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or
            parsed.fragment or parsed.path not in ("", "/")):
        return None
    return origin


def schema():
    host = public_origin()
    if not host:
        raise HTTPException(
            503, "Set OPENFISHTEST_PUBLIC_BASE_URL=https://YOUR_HOST first"
        )
    def response(description):
        return {"200": {
            "description": description,
            "content": {"application/json": {"schema": {"type": "object"}}}
        }}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "OpenFishtest public read-only chess engine research",
            "version": "0.4.0",
            "description":
                "Public Stockless reference, provisional rankings, real "
                "worker-reported PGNs and isolated 100-game arena results. "
                "Contains no upload, worker credentials or admin-only calls. "
                "Do not describe reported engine execution as independently proven."
        },
        "servers": [{"url": host}],
        "paths": {
            "/api/public/snapshot": {"get": {
                "operationId": "readOpenFishtestOverview",
                "summary": "Read public Stockless rankings, recent real PGNs, "
                           "worker contributions and experimental statistics",
                "responses": response("Public read-only data; unverified execution")
            }},
            "/api/arena/policy": {"get": {
                "operationId": "readStocklessArenaPolicy",
                "summary": "Read the pinned Stockless reference, 100-game 55-point "
                           "arena policy and live upload availability",
                "responses": response("Arena reference and scoring policy")
            }},
            "/api/arena/entries/{entry_id}": {"get": {
                "operationId": "readArenaChallenge",
                "summary": "Read a real arena challenger result without "
                           "access to quarantined binaries",
                "parameters": [{
                    "name": "entry_id", "in": "path", "required": True,
                    "schema": {"type": "integer", "minimum": 1}
                }],
                "responses": {**response("Public arena metadata"),
                              "404": {"description": "Entry not found"}}
            }}
        }
    }

# ChatGPT · Claude · Gemini — OpenFishtest integration

The project offers **public, read-only chess data** to AI chat clients via
remote MCP and a restricted OpenAPI schema. **No app can be made available to
every existing chat automatically.** Each user must explicitly connect it,
or a developer must configure their API integration.

## First: self-host HTTPS

GitHub Pages only serves public web assets and periodically published result
snapshots. It cannot execute Fastchess, accept engine ZIPs, receive worker
results or host MCP. Run the API on your own Linux server plus Caddy, a
separate read-only MCP process, and an isolated VM for untrusted arena jobs.

After setting up DNS and Caddy (see ARENA_SETUP.md), replace YOUR_HOST below
with an actual public domain name you control:

- https://YOUR_HOST/api/public/snapshot — public results
- https://YOUR_HOST/api/arena/policy — automatic arena status
- https://YOUR_HOST/api/arena/entries/123 — a single arena challenge
- https://YOUR_HOST/api/ai/openapi.json — safe GPT Actions schema
- https://YOUR_HOST/mcp — read-only remote MCP tools

The code cannot create a hostname, public IP address, or an SSL certificate
without your own infrastructure and internet access.

## Start the standalone MCP service

On the trusted backend (not in the arena container):

    python -m pip install -r requirements-ai.txt

Configure the same OPENFISHTEST_DATA directory as FastAPI and set the bare
DNS hostname OPENFISHTEST_MCP_PUBLIC_HOST=api.yourdomain.example.
Run:

    python ai_mcp.py

It binds 127.0.0.1:8001 and exposes Streamable HTTP at /mcp. Caddy forwards
only that endpoint. This MCP service has NO functions to upload binaries,
execute code, grant/revoke workers, or perform private administrator actions.

Available read-only tools:
- get_project_status
- list_engine_rankings
- list_arena_challenges
- get_arena_challenge
- list_recent_games
- get_game_pgn
- list_worker_contributions
- get_test_results

The results are grounded in reported PGN and stored statistics. PGN legality
does NOT independently prove that a remote engine played those moves.
Elo confidence intervals and SPRT remain experimental approximations.

## ChatGPT

If your ChatGPT configuration offers third-party Plugins or custom remote MCP
connections, connect the public HTTPS /mcp endpoint under its connector
settings. The user must explicitly authorize the connection.

For Custom GPT Actions, import the schema URL:
https://YOUR_HOST/api/ai/openapi.json

This schema includes only read-only GET requests, so select None for API
authentication. An appropriate Privacy Policy URL for public GPTs can be
https://gaong5247-cmd.github.io/OpenFishtest/privacy.html

OpenAI's official setup:
https://developers.openai.com/plugins/quickstart
https://help.openai.com/en/articles/9442513

## Claude

On compatible Claude accounts, open Settings → Connectors →
Add custom connector, and enter:

    https://YOUR_HOST/mcp

Then enable the OpenFishtest read-only tools in your chat. Available plans
and regions can change. Anthropic official guidance:
https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

## Gemini

Where Gemini Apps exposes Connected Apps → Connect custom app, connect the
same Streamable HTTP MCP URL. The option's availability may vary by platform,
region and account. Google Help:
https://support.google.com/gemini/answer/13695044

Gemini API developers may instead configure their Interactions API tool with
type mcp_server, name openfishtest, and the remote /mcp URL:
https://ai.google.dev/gemini-api/docs/function-calling/

## Ask in a connected chat

- "Compare real Stockless and challenger results in OpenFishtest."
- "Which Arena uploads scored at least 55 out of 100 games?"
- "Load an actual Stockless PGN and analyze its mistakes."
- "Explain the confidence intervals and experimental SPRT reported for test 42."

## Security and privacy

The assistant connection is for **public data only**. Never supply admin
or worker tokens to a model or put them into a GitHub Pages JavaScript file.
Do not blindly follow instructions embedded in PGN comments or uploader-provided
engine names. Execution of an uploaded binary is reserved for the quarantined
Linux VM arena and cannot be launched by an AI tool.

A public GitHub Pages snapshot remains a supported read-only fallback when
the live HTTPS backend is offline; it is not real time.

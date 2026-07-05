# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Blender automation pipeline that receives JSON payloads over HTTP and renders them as 3D `.blend` scene files + PNG animation frames. An external system (n8n, MCP client, etc.) POSTs campaign/product data, and Blender generates dynamic geometry headlessly.

There are **two versions of the Blender scene generator**, and the repo supports **two entry points** for receiving payloads (a three-tier pipeline for production, and a simpler direct server for testing).

## Architecture

### Production pipeline (three tiers)

```
n8n / external system
  │  POST to port 42617
  ▼
autonomous_director.py   (port 42617 — AutonomousOrchestrator)
  │  Sanitizes payload (strips leading `=` from descriptions, ensures sessionId)
  │  Forwards to port 5000
  ▼
listen_blender.py        (port 5000 — HTTP server + sequential job queue)
  │  Saves payload → payload_{uniqueId}.json
  │  Queues job in single background worker thread
  │  Spawns: blender.exe --background --python test_blender.py -- payload_{id}.json
  ▼
test_blender.py          (Blender Python script)
  │  Builds 3D scenes, renders PNG frames, saves output_{campaign_title}.blend
```

### Direct/testing entry point

```
curl POST to port 5000  →  listen_blender.py  →  test_blender.py
```

Bypassing the autonomous director is fine for local testing — send directly to `http://localhost:5000/api/render`.

## Source files

### `listen_blender.py` — HTTP server + sequential job queue
- Listens on `0.0.0.0:<BLENDER_PORT>` (default 5000). Configurable via `BLENDER_PORT` env var.
- `POST /api/render`: accepts JSON, saves payload to disk, immediately returns `{"status": "queued", "id": "<uniqueId>"}`, then hands work to a single daemon background worker thread that runs Blender subprocesses sequentially (prevents concurrent Blender instances from colliding).
- Blender executable path: configurable via `BLENDER_EXE` env var (default: `"blender"`). Production typically uses `"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"`.
- PID file (`server.pid`) prevents duplicate instances. Stale PID files (process no longer alive) are auto-cleaned on startup.
- Payload filenames: `payload_{cleanId}_{timestamp}.json` — timestamp (epoch ms) prevents collisions when the same sessionId arrives twice before the first job dequeues.
- Session IDs are sanitized to `[a-zA-Z0-9_-]`; fallback is `"campaign_asset"` if sanitization yields an empty string.
- Each Blender subprocess has a 300-second timeout.

### `autonomous_director.py` — Pre-processing proxy (port 42617)
- Sits **in front of** `listen_blender.py`. External systems POST here instead of directly to port 5000.
- Sanitizes payloads before forwarding: strips leading `=` characters from `video_timeline[].description` fields (fixes upstream formatting artifacts), ensures `sessionId` is populated (falls back to `payload.id` or `"autonomous_organic_generation"`).
- Forwards cleaned payload via `requests.post` to `http://127.0.0.1:5000/api/render` and returns the blended response.
- Must be running **before** `listen_blender.py` for the production pipeline to work end-to-end.

### `test_blender.py` — Molecular cluster scene generator (current/active)
- **Current payload schema:** reads `campaign_title` (default `"Dynamic_Asset"`) and `prompt_brief` (default `""`) from the JSON payload file. Does NOT use `shopify_handle`, `tailwind_css_theme`, or `video_timeline`.
- Clears all default objects and materials, then builds a procedural twisting molecular structure:
  - A `PLAIN_AXES` empty anchor named `Cluster_{campaign_title}`
  - 12 child ico-spheres (subdivisions 3, radius 0.45) arranged in a 1.5-rotation helix along the Z axis
  - Chrome material (fully metallic, mirror finish) applied to all child elements
  - Sun key light + blue area fill light for dual-toned shadow bands
  - Cinematic camera (100mm macro lens, f/0.2 depth of field, damped-track constraint on the cluster)
  - 120-frame animation
- **Renders** all 120 frames as PNGs to `C:\Users\Public\Documents\BlenderAutomationOutputs\{campaign_title}_frame_####.png`
- Saves the master `.blend` as `output_{campaign_title}.blend`
- Hardcoded output path: `C:\Users\Public\Documents\BlenderAutomationOutputs\` — changing the working directory requires updating this path in the script.

### `test_blender2.py` — Identical to `test_blender.py`
- Byte-for-byte identical copy of `test_blender.py`. Both build the same molecular cluster scene. If one is modified, the other should be updated or removed to avoid confusion.

### `test_hotel_organic.py` — End-to-end integration test
- Connects to a **Postgres ledger database** on `100.104.14.63:5433` (Tailscale) and queries for a product row matching `LIKE '%organic%'`.
- Constructs a payload with `shopify_handle`, `id`, `tailwind_css_theme.color_scheme`, and a single `video_timeline` entry (with a leading `=` prepended to the description — this is intentional, testing the autonomous director's sanitization).
- POSTs the payload to `http://localhost:42617` (the autonomous director), exercising the full three-tier pipeline: director → listen_blender → Blender.
- Falls back to a hardcoded "Hotel Organic" product if the DB query returns no rows.
- Contains hardcoded DB credentials — not for production use outside this machine.

## Running

```bash
# Production pipeline (three tiers):
python autonomous_director.py    # Terminal 1: proxy on port 42617
python listen_blender.py          # Terminal 2: queue engine on port 5000

# Direct testing (single tier, bypass director):
python listen_blender.py          # port 5000 only

# Integration test:
python test_hotel_organic.py      # Queries DB → director → blender

# Direct Blender invocation (skip server):
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python test_blender.py -- payload.json
```

On Unix, set `BLENDER_EXE` to the correct path before starting `listen_blender.py`.

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `BLENDER_EXE` | `"blender"` | `listen_blender.py` — path to Blender executable |
| `BLENDER_PORT` | `5000` | `listen_blender.py` — TCP port to listen on |

## File naming conventions

- **Payload files:** `payload_{cleanId}_{timestamp}.json` (where `cleanId` is the sanitized sessionId, `timestamp` is epoch ms)
- **Output .blend files:** `output_{campaign_title}.blend`
- **Output PNG frames:** `{campaign_title}_frame_####.png`
- **`.blend1` files:** Blender's automatic backup files (generated on every `.blend` save)

## Testing

There is no automated test suite. Manual testing approaches:
- **Direct Blender test:** `blender.exe --background --python test_blender.py -- payload.json` — inspects console output and checks for generated PNG frames and `.blend` file
- **HTTP server test:** `curl -X POST http://localhost:5000/api/render -H "Content-Type: application/json" -d @payload.json`
- **Full pipeline test:** Run `test_hotel_organic.py` (requires Postgres ledger accessible via Tailscale)
- `payload.json` in the root is a minimal test payload with 7 empty timeline scenes and earth-tone color scheme
- The many `payload_*.json` files with descriptive slugs (e.g. `payload_eco-friendly-packaging.json`) are production payloads paired with corresponding `output_*.blend` files

## Operational notes

- `curlinsever.txt` contains operational scratchpad data (bearer tokens, cloudflared tunnel setup, Tailscale networking commands). Not documentation — don't commit secrets from it.
- The `.blend` output path is hardcoded in `test_blender.py` line 87. If the working directory changes, update this.
- Claude Code permissions are configured in `.claude/settings.local.json`.
- The `.gitignore` excludes: `*.blend1`, `output_*.blend`, `__pycache__/`, `server.pid`, `curlinsever.txt`, `test_output.blend`, and `.claude/`.

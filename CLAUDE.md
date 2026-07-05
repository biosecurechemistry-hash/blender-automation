# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Blender automation pipeline that receives JSON payloads over HTTP and renders them as 3D `.blend` scene files + PNG animation frames. An external system (n8n, MCP client, etc.) POSTs campaign/product data, and Blender generates dynamic geometry headlessly.

There are **two versions of the Blender scene generator**, and the repo supports **two entry points** for receiving payloads (a three-tier pipeline for production, and a simpler direct server for testing).

## Architecture

### Production pipeline (three tiers with post-render hook)

```
n8n / external system
  │  POST to port 42617
  ▼
autonomous_director.py   (port 42617 — AutonomousOrchestrator)
  │  ├─ Sanitizes payload
  │  ├─ Forwards to port 5000 → returns 200 immediately
  │  └─ Background hook (daemon thread):
  │       ├─ Phase 1: Poll output dir for frame completion
  │       ├─ Phase 2: Verify frame integrity (count, size, zero-byte)
  │       ├─ Phase 3: VLC playback verification
  │       └─ Phase 4: Shopify staging (hidden)
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

### `autonomous_director.py` — Full-cycle orchestrator (port 42617)

Sits **in front of** `listen_blender.py`. External systems POST here instead of directly to port 5000. Now a full-cycle orchestrator — not just a proxy.

**Request flow (synchronous, returns immediately):**
1. Sanitizes payload (strips leading `=` from `video_timeline[].description`, ensures `sessionId`)
2. Forwards to `listen_blender.py` on port 5000
3. Returns `{"status": "queued", "id": "<queueId>", "hook_active": true}`

**Post-render hook (asynchronous, daemon thread):**

| Phase | Action | Timeout |
|---|---|---|
| 1. Poll | Watch `{campaign_title}_frame_*.png` count until `frame_end - frame_start + 1` reached | 900s |
| 2. Verify | Check file count, total bytes, zero-byte detection | — |
| 3. VLC | `vlc_status()`, play first frame, queue full sequence, pause for review | — |
| 4. Shopify | POST to `/api/publish_auto` with `status: hidden` | 10s |

**Environment variables:**

| Variable | Default | Purpose |
|---|---|---|
| `DIRECTOR_PORT` | `42617` | Listening port |
| `DIRECTOR_POLL_INTERVAL` | `5.0` | Seconds between frame-count checks |
| `DIRECTOR_POLL_TIMEOUT` | `900.0` | Max seconds to wait for render |
| `VLC_HOST` / `VLC_PORT` / `VLC_PASS` | `localhost:8080` / `""` | VLC HTTP interface |
| `SHOPIFY_PUBLISH_URL` | `100.104.14.63:3002/api/publish_auto` | Shopify buffer endpoint |
| `RENDER_OUTPUT_DIR` | `C:\Users\Public\...` | Directory scanned for frames |

### `test_blender.py` — Dynamic scene generator (all properties from payload)

All scene properties are driven by the JSON payload. Every field is optional with sensible defaults — existing `{campaign_title, prompt_brief}`-only payloads continue to work unchanged.

**Payload schema (all fields optional):**

| Field | Default | Description |
|---|---|---|
| `campaign_title` | `"Dynamic_Asset"` | Prefix for output filenames |
| `prompt_brief` | `""` | Logged to Blender stdout for traceability |
| `geometry` | `"helix"` | Shape preset: `helix`, `grid`, `sphere`, `ring` |
| `material` | `"chrome"` | Material preset: `chrome`, `matte`, `glass`, `emissive`, `gold` |
| `lighting` | `"studio"` | Light rig preset: `studio`, `warm`, `dramatic`, `soft` |
| `frame_start` | `1` | First animation frame |
| `frame_end` | `120` | Last animation frame |
| `fps` | `24` | Frames per second |
| `camera_lens` | `100` | Focal length in mm |
| `camera_fstop` | `0.2` | Depth of field aperture |
| `camera_distance` | `9.0` | Camera Z-distance from origin |
| `camera_height` | `2.0` | Camera elevation |
| `resolution_x` | `1920` | Render width |
| `resolution_y` | `1080` | Render height |
| `resolution_percentage` | `100` | Render scale % |
| `color_primary` | `null` | RGBA tuple to override material base color |
| `elements_count` | `12` | Number of elements (helix/grid/sphere) |
| `cluster_radius` | `1.8` | Radial spread of elements |
| `element_radius` | `0.45` | Size of each element |
| `subdivisions` | `3` | Ico-sphere detail level |
| `rotations` | `1.5` | (helix only) Number of full twists |
| `z_height` | `4.0` | (helix only) Vertical climb |
| `grid_spacing` | `1.5` | (grid only) Cell spacing |
| `element_size` | `0.6` | (grid only) Cube size |
| `rings` | `3` | (ring only) Number of rings |
| `elements_per_ring` | `12` | (ring only) Elements per ring |
| `ring_spacing` | `1.8` | (ring only) Vertical gap between rings |
| `output_dir` | `C:\Users\Public\...` | Output directory for frames and .blend |
| `render_animation` | `true` | Set `false` to skip PNG frame rendering |
| `save_blend` | `true` | Set `false` to skip .blend save |

**Geometry presets:**
- **helix** — twisting chain of ico-spheres climbing the Z axis
- **grid** — flat array of cubes for product-grid visuals
- **sphere** — Fibonacci-sphere distribution for molecular/particle looks
- **ring** — concentric rings at varying heights for orbital/product-line layouts

**Material presets:**
- **chrome** — fully metallic, mirror finish (roughness 0.05)
- **matte** — non-metallic, soft diffuse (roughness 0.7)
- **glass** — full transmission, IOR 1.45
- **emissive** — warm orange self-illumination, strength 2.0
- **gold** — metallic warm gold (roughness 0.1)

**Lighting presets:**
- **studio** — neutral sun + blue fill (default)
- **warm** — stronger sun + warm orange fill
- **dramatic** — very strong key, minimal fill for high contrast
- **soft** — low sun + strong cool fill for product shots

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

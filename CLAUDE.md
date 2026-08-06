# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Blender automation pipeline that receives JSON payloads over HTTP and renders them as 3D `.blend` scene files + PNG animation frames. An external system (n8n, MCP client, etc.) POSTs campaign/product data, and Blender generates dynamic geometry headlessly using **Cycles with GPU acceleration and denoising**.

There are **two entry points** for receiving payloads: a three-tier production pipeline (autonomous director → queue server → Blender) and a simpler direct server for testing.

## Architecture

### Production pipeline (three tiers with post-render hook)

```
n8n / external system
  │  POST to port 42617
  ▼
autonomous_director.py   (port 42617 — AutonomousOrchestrator)
  │  ├─ Sanitizes payload (strips leading = from descriptions, ensures sessionId)
  │  ├─ Forwards to port 5000 → returns {"status":"queued","id":"...","hook_active":true}
  │  └─ Background hook (daemon thread):
  │       ├─ Phase 1: Poll campaign_<id>/frames/ for PNG frame completion
  │       ├─ Phase 2: Verify frame integrity (count, total bytes, zero-byte detection)
  │       ├─ Phase 3: VLC playback verification (play first frame, queue full dir, pause)
  │       └─ Phase 4: Shopify staging (POST to /api/publish_auto with status: hidden)
  ▼
listen_blender.py        (port 5000 — HTTP server + sequential job queue)
  │  Saves payload → payload_{cleanId}_{timestamp}.json
  │  Queues job in single background worker thread (prevents concurrent Blender GPU access)
  │  Spawns: blender.exe --background --python test_blender.py -- payload_{id}.json
  ▼
test_blender.py          (Blender Python script)
  │  Builds 3D scenes with Cycles GPU, renders PNG frames to campaign_<id>/frames/
  │  Saves .blend to campaign_<id>/_blend/
```

### Direct/testing entry point

```
curl POST to port 5000  →  listen_blender.py  →  test_blender.py
```

Bypassing the autonomous director is fine for local testing — send directly to `http://localhost:5000/api/render`.

### MCP bridge (Claude Code integration)

```
blender_mcp_bridge.py    (stdio JSON-RPC server — registered as an MCP server)
  │  Exposes 9 tools via stdio transport:
  │    run_pipeline      — POST payload to listen_blender or spawn Blender directly
  │    modify_scene      — Inject arbitrary Python into a headless Blender to mutate scenes
  │    get_scene_info    — Open a .blend headless and dump objects, materials, cameras, lights
  │    generate_image    — Stable Diffusion image gen via sd-cli.exe (Open-Generative-AI)
  │    generate_video    — Stable Diffusion video gen via sd-cli.exe vid_gen mode
  │    list_assets       — Scan OGA blob_storage + Blender render frames (by campaign)
  │    studio_status     — Health check for OGA app, SD models, Blender outputs
  │    vlc_control       — Control VLC playback via Lua HTTP interface (play, pause, seek)
  │    remote_services   — Health check for kaliko-hosted services (WebUI, Ghostfolio, DB, Shopify)
```

### Director-Server (Next.js island dashboard)

```
Director-Server/          (self-contained Next.js project, isolated from broken monorepo)
  │  NOTE: npm scripts (dev/start/build) run test_ledger.js or no-op — the Next.js
  │        dev server is NOT started by any script; pages exist but are not currently served.
  │  lib/db.js            — PostgreSQL connection pool for director_ledger :5433
  │  pages/index.js       — Dashboard UI: ledger, Blender bridge, Open WebUI, ZeroClaw,
  │                         Ghostfolio, Shopify cards. Displays "molecular_sweep.py" as the
  │                         Blender script label, but the actual pipeline uses test_blender.py.
  │  pages/agent/index.js — ZeroClaw Agent dashboard (Inquisitor/Scout status, pipeline health,
  │                         command queue)
  │  pages/api/ledger-summary.js — GET endpoint returning pending/total/table counts
  │  test_ledger.js       — Direct PG connection test (connect, list tables, count rows/services)
  │  next.config.js       — Island-strategy Webpack config: resolves ONLY from local node_modules,
  │                         blocks monorepo workspace symlinks, aliases React to single instance
  │  generate_logo_scene.py — Blender Python script: imports logo SVGs from 2Dti3D/Logo/,
  │                         builds extruded/beveled 3D logo curves with gold material,
  │                         adds "Au"/"S" matrix cube tiles, sets up lighting + camera.
  │                         Scene setup only (no render call). Run via:
  │                         blender.exe --background --python Director-Server/generate_logo_scene.py
  │  start_wan.bat        — Wan2GP launcher (external tool, not part of core pipeline)
  │  listen_blender.py    — Separate "Kali Linux Island Edition" variant (259 lines vs 176 in root);
  │                         different docstring but same core HTTP→Blender spawn logic
  │
  │  Deployment files:
  │  Production.Dockerfile — node:20-slim + Python build tools, exposes 3002.
  │                          ⚠️ Stale: CMD runs "pure-backend.js" which does not exist.
  │  SETUP.sh              — Kali Linux island-setup script: purges monorepo symlinks,
  │                          npm install --no-workspaces, starts Postgres Docker container
  │                          (port 5433:5432), runs test_ledger.js, starts Next.js on port 8081.
  │                          Contains hardcoded Postgres credentials matching lib/db.js.
  │  .railwayignore        — Ignores node_modules, .next, .git, *.png, *.blend, *.blend1.
  │  railway.json          — REMOVED (was used for Railway/Nixpacks deploys; no longer needed).
```

**npm scripts (from package.json):**

```bash
npm run dev           # Runs node test_ledger.js (NOT the Next.js dev server)
npm run build         # No-op: echoes "Bypassing Next.js frontend compilation"
npm start             # Runs node test_ledger.js
npm run test:ledger   # Direct PG connection test via test_ledger.js
npm run test:blender  # Smoke test: curls port 5000 with 320×180 2-frame payload
```

**next.config.js island strategy:**
- `resolve.modules`: forced to `Director-Server/node_modules` only — never looks up at parent
- `resolve.symlinks`: `false` — blocks broken monorepo workspace symlinks
- React singleton: aliases `react` and `react-dom` to local copies to prevent duplicate React errors
- Server externals: `pg`, `pg-native`, `dns`, `net`, `tls`, `fs` are never bundled
- Watch ignore: parent `packages/`, `node_modules/`, `.git/` excluded from file watching
- Browser env vars (with defaults):
  - `NEXT_PUBLIC_OPEN_WEBUI_URL` → `http://127.0.0.1:3333`
  - `NEXT_PUBLIC_ZEROCLAW_URL` → `http://127.0.0.1:42617/agent`
  - `NEXT_PUBLIC_BLENDER_API` → `http://127.0.0.1:5000`

### Video compilation (post-render)

```
compile_video.py          — Blender VSE script: imports PNG sequence + WAV voiceover,
                            renders H.264 MP4 via FFmpeg (campaign 52580 hardcoded)
compile_final.py          — Standalone Python: PIL converts PNG frames to raw RGB24 temp file,
                            ffmpeg compiles with libopenh264 + AAC (avoids pipe deadlock)
```

### Utility scripts

```
cell_watcher.py           — Simple folder watcher: polls a directory for new/modified files,
                            spawns autonomous_director.py when activity is detected
organize.py               — One-shot organizer: sweeps root for payload_*.json, *_frame_*.png,
                            output_*.blend and moves them into campaign_payloads/,
                            rendered_frames/, blender_projects/ subdirectories
test_hotel_organic.py     — End-to-end integration test: queries Postgres ledger for "organic"
                            product, builds payload (with intentional leading =), POSTs to
                            autonomous_director on port 42617. Falls back to hardcoded product.
generate_music.py         — MiniMax Music 3.0 API client: POSTs an instrumental ambient-music
                            prompt to api.minimax.io/v1/music_generation (model: music-3.0),
                            prints JSON response with download URL. Hardcoded for the
                            Himalayan Salt Inhaler / Hotel Organic campaign aesthetic.
                            ⚠️ Contains a hardcoded API key — extract to env var before reuse.
```

### Data artifacts (non-code)

```
Muapi/                    — Scratch directory for Google Ads optimization-score reports
                            and generated media assets (MP4). Not operational code.
                            Recommend adding to .gitignore.
staged_dashboard_34518.json — Staging-dashboard snapshot for GOLD-queued product #34518
                            (Dead Sea Salt Bath Soak). Contains db_id, session_id,
                            blender_queue_id, SEO blog template, and deployment blockers.
```

## Campaign subfolder output structure

Each render is isolated in `campaign_<id>/` (where `id` is `campaign_id` from the payload or a slug of `campaign_title`):

```
campaign_52580/
  frames/          — PNG frame sequences (instantly scannable)
  _blend/          — .blend + any .blend1 backups (isolated from frames)
  _audio/          — generated audio assets (voiceover WAVs)
  _cache/          — transient files, cleaned post-render
  _images/         — Stable Diffusion generated images (routed by MCP bridge)
  _video/          — compiled MP4 output

campaign_salt_inhaler/   (manual pipeline — not rendered via test_blender.py)
  _models/         — source OBJ/GLB mesh files (trimesh exports)
  _exports/        — intermediate .blend, OBJ, STL, FBX exports
  _blend/          — final .blend scene files
  _video/          — compiled MP4 turntable output
  frames/          — PNG turntable frame sequences
```

Legacy files in the flat root directory still work — the pipeline scans both new campaign folders and the flat root.

## Campaign payload storage

`campaign_payloads/` organizes JSON payloads by campaign name slug. Each campaign has its own subdirectory (e.g., `campaign_payloads/eco-friendly-packaging/payload_eco-friendly-packaging.json`). The `campaign_payloads/dynamic/` subdirectory holds auto-generated test payloads with epoch timestamps.

## Source files

### `listen_blender.py` — HTTP server + sequential job queue
- Listens on `0.0.0.0:<BLENDER_PORT>` (default 5000). Configurable via `BLENDER_PORT` env var.
- `POST /api/render`: accepts JSON, saves payload to disk, immediately returns `{"status": "queued", "id": "<uniqueId>"}`, then hands work to a single daemon background worker thread that runs Blender subprocesses sequentially (prevents concurrent Blender GPU instances from colliding).
- Blender executable path: configurable via `BLENDER_EXE` env var (default: `"blender"`). Production typically uses `"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"`.
- PID file (`server.pid`) prevents duplicate instances. Stale PID files (process no longer alive) are auto-cleaned on startup.
- Payload filenames: `payload_{cleanId}_{timestamp}.json` — timestamp (epoch ms) prevents collisions when the same sessionId arrives twice before the first job dequeues.
- Session IDs are sanitized to `[a-zA-Z0-9_-]`; fallback is `"campaign_asset"` if sanitization yields an empty string.
- Each Blender subprocess has a 300-second timeout.

### `autonomous_director.py` — Full-cycle orchestrator (port 42617)

Sits **in front of** `listen_blender.py`. External systems POST here instead of directly to port 5000.

**Request flow (synchronous, returns immediately):**
1. Sanitizes payload (strips leading `=` from `video_timeline[].description`, ensures `sessionId`)
2. Forwards to `listen_blender.py` on port 5000
3. Returns `{"status": "queued", "id": "<queueId>", "hook_active": true}`

**Post-render hook (asynchronous, daemon thread):**

| Phase | Action | Timeout |
|---|---|---|
| 1. Poll | Watch `campaign_<id>/frames/` for `{title}_frame_*.png` count until `frame_end - frame_start + 1` reached | 900s |
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

### `blender_mcp_bridge.py` — MCP stdio server (Claude Code integration)

A JSON-RPC server that communicates over stdin/stdout using the Model Context Protocol. Registered with Claude Code via `claude mcp add blender --transport stdio`. Exposes 9 tools across three domains:

**Blender tools:**
- `run_pipeline` — POST payload to listen_blender.py port 5000; falls back to spawning Blender directly if the server is down
- `modify_scene` — Open a .blend headless, inject arbitrary Python (full bpy access), save
- `get_scene_info` — Dump scene metadata: objects (name, type, location, parent/child), meshes, materials (with node info), cameras (lens, DOF), lights (type, energy, color), active camera, render settings

**Open-Generative-AI tools:**
- `generate_image` / `generate_video` — Invoke sd-cli.exe with the bundled ae.safetensors model. Both accept `campaign_id` to route outputs into `campaign_<id>/_images/` or `_video/`
- `list_assets` — Scan OGA blob_storage and Blender render frames, grouped by campaign prefix
- `studio_status` — Health check: SD binaries, installed models, blob storage usage, render counts, listen_blender liveness

**Integration tools:**
- `vlc_control` — Full VLC Lua HTTP interface: status, play, pause, stop, next, prev, fullscreen, play_file (with directory-of-frames support for frame-by-frame review), seek, volume, loop
- `remote_services` — Health check for kaliko-hosted services via Tailscale: Open WebUI (3335), Ghostfolio (3334), shopify-publish (3002), blender-api (3006), director-mcp (8000), Postgres (5433)

### `test_blender.py` — Dynamic scene generator (all properties from payload)

All scene properties are driven by the JSON payload. Every field is optional with sensible defaults.

**Rendering:** Cycles engine with GPU acceleration, 128 samples, OpenImageDenoise enabled. Uses an HDRI environment texture (`studio.exr`) for realistic reflections.

**Animation:** The cluster anchor is rotated 360° across the frame range with linear interpolation.

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

### `test_blender2.py` — Older variant of `test_blender.py`
- ~36 lines shorter than `test_blender.py`. Missing: Cycles/GPU rendering setup, HDRI environment texture loading, and 360° turntable animation keyframes. Likely an older or intermediate version — `test_blender.py` is the canonical scene generator.

### Inhaler pipeline (Himalayan Salt Inhaler — manual/offline workflow)

Unlike the automated JSON→render pipeline, the inhaler workflow is a set of standalone Blender Python scripts for 2.5D depth-scan→3D reconstruction, mesh cleanup, turntable animation, and video compilation. All paths are hardcoded to `campaign_salt_inhaler/`.

**2.5D Image+Depth → 3D Mesh:**
- `pipeline_2d5_to_3d.py` — Complete 20-step pipeline: source image → depth reconstruction → mesh cleanup → PBR materials → turntable animation → multi-format export
- `cleanup_depth_scan.py` — Import depth-scan OBJ, isolate primary artifact, remove noise, fill holes, make manifold, fix normals, export OBJ+STL
- `reconstruct_cylindrical.py` — Extract silhouette profile from depth-map reference, lathe/revolve into smooth cylindrical body (lathe-from-profile approach)
- `reconstruct_v2.py` — Rebuild inhaler from known product dimensions rather than depth data (15cm body with taper, mouthpiece, base collar, air port)

**Mesh import + render:**
- `render_inhaler.py` — Import trimesh-generated OBJ, set up studio lighting + camera, render preview still, save .blend
- `render_inhaler_v2.py` — Corrected-mesh version with proper 360° Z-axis turntable, 72 frames at 5° steps, real-world cm scale
- `animate_inhaler.py` — Load existing inhaler .blend, add 360° Z-axis rotation keyframes, render full PNG sequence
- `fix_and_render_pipe.py` — Load high-quality scan mesh, normalize scale/rotation/position, studio light + turntable render
- `fix_imagetostl_render.py` — Complete imagetostl.com pipeline: load heightfield OBJ, clean topology, extrude/revolve for 3D volume, 72-frame turntable, compile H.264 MP4 via Blender VSE
- `render_cleaned_turntable.py` — Turntable render of cleaned artifact .blend
- `save_blend_scene.py` — Rebuild scene from imagetostl mesh, save .blend only (skip render)
- `mcp_scene_setup.py` — 7-step scene setup (wipe, ground plane, lighting, camera, etc.) driven via MCP

**Video compilation (inhaler-specific):**
- `compile_h264.py` — Compile PNG frames → H.264 MP4 via Blender VSE (targets `campaign_salt_inhaler/frames/`)

### `Modly/` — ML/3D tooling subproject
- Contains a Python venv and two key components not directly integrated into the primary pipeline:
  - `modly_mcp_bridge.py` — A separate stdio MCP server (register with `claude mcp add modly`) that connects to Ollama (`qwen2.5-coder:3b`) for AI-assisted 3D mesh code generation, executes trimesh scripts, exports OBJ/GLB/STL, and scans workspace assets
  - `generate_inhaler.py` — Procedural trimesh generator for the Himalayan Salt Inhaler product (real-world dimensions, salt crystal geometry)
- `Experiment/` contains OBJ meshes from pipe scans and Google Drive imports
- `workspace/` contains reference images, generated meshes, `_generated_mesh.py` scripts, and ComfyUI workflow JSON files
- `workflows/` contains ComfyUI workflow JSON files (~657 KB) referencing images in `workspace/` for AI image generation
- `extensions/` and `models/` are empty (placeholders)

### `2Dti3D/` — Texture-manifest batch rendering (separate automation flow)
- `automation_script.py` — Blender Python script that loads a `textureManifest.js` file (product name + image URL pairs scraped from Shopify), iterates through products, and renders each in Blender
- `textureManifest.js` — Auto-generated manifest of ~49+ products with Shopify CDN image URLs
- `Renders/` — Thousands of rendered PNG frames from batch product renders
- `Logo/` — Hotel Organic brand logo source files (`logoHO.svg`, `logoHO.png`, `logoHO_transparent.png`, `fav_h_o.svg`, `fav_h_o.png`). Input source for `Director-Server/generate_logo_scene.py`.

### `Production_last_chance/` — Database dump snapshots
- Contains 56+ JSON files dumped from the `director_ledger` Postgres database (rows from `director_ledger`, `scene_compositions`, `orchestration_jobs`, `production_assets`, `service_registry`, etc.)
- Also includes `pg_roles_dump.txt`, `generated_assets.json`, and scene composition exports
- Reference/recovery data — not part of any pipeline

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

# MCP bridge (register with Claude Code):
claude mcp add blender --transport stdio -- \
    "C:\Program Files\Blender Foundation\Blender 5.1\5.1\python\bin\python.exe" \
    "C:\Users\Public\Documents\BlenderAutomationOutputs\blender_mcp_bridge.py"

# Director-Server database test:
cd Director-Server && npm run test:ledger

# Blender smoke test (via npm script):
cd Director-Server && npm run test:blender
```

On Unix, set `BLENDER_EXE` to the correct path before starting `listen_blender.py`.

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `BLENDER_EXE` | `"blender"` | `listen_blender.py` — path to Blender executable |
| `BLENDER_PORT` | `5000` | `listen_blender.py` — TCP port to listen on |
| `DIRECTOR_PORT` | `42617` | `autonomous_director.py` — TCP port to listen on |
| `DIRECTOR_POLL_INTERVAL` | `5.0` | `autonomous_director.py` — frame polling interval |
| `DIRECTOR_POLL_TIMEOUT` | `900.0` | `autonomous_director.py` — max seconds to wait for render |
| `VLC_HOST` / `VLC_PORT` / `VLC_PASS` | `localhost:8080` / `""` | `autonomous_director.py`, `blender_mcp_bridge.py` |
| `SHOPIFY_PUBLISH_URL` | `100.104.14.63:3002/api/publish_auto` | `autonomous_director.py` |
| `RENDER_OUTPUT_DIR` | `C:\Users\Public\...` | `autonomous_director.py`, `blender_mcp_bridge.py` |
| `KALIKO_HOST` | `100.104.14.63` | `blender_mcp_bridge.py` — remote services health check |

## File naming conventions

- **Payload files:** `payload_{cleanId}_{timestamp}.json` (where `cleanId` is the sanitized sessionId, `timestamp` is epoch ms)
- **Output .blend files:** `output_{campaign_title}.blend` (inside `campaign_<id>/_blend/`)
- **Output PNG frames:** `{campaign_title}_frame_####.png` (inside `campaign_<id>/frames/`)
- **`.blend1` files:** Blender's automatic backup files (suppressed via `save_version = 0` in test_blender.py; cleaned post-render)

## Testing

There is no automated test suite. Manual testing approaches:
- **Direct Blender test:** `blender.exe --background --python test_blender.py -- payload.json` — inspects console output and checks for generated PNG frames and `.blend` file
- **HTTP server test:** `curl -X POST http://localhost:5000/api/render -H "Content-Type: application/json" -d @payload.json`
- **Smoke test (fast):** `npm run test:blender` (in Director-Server/) — POSTs a minimal 320×180, 2-frame payload to port 5000; quick pipeline verification without rendering full-HD frames
- **Full pipeline test:** Run `test_hotel_organic.py` (requires Postgres ledger accessible via Tailscale)
- **MCP bridge test:** The MCP bridge is tested implicitly through Claude Code tool invocations
- **Director-Server DB test:** `cd Director-Server && node test_ledger.js`
- `payload.json` in the root is a minimal test payload with 7 empty timeline scenes and earth-tone color scheme
- `campaign_payloads/` contains production payloads organized by campaign name slug

## Operational notes

- `curlinsever.txt` contains operational scratchpad data (bearer tokens, cloudflared tunnel setup, Tailscale networking commands). Not documentation — don't commit secrets from it.
- **HDRI dependency:** `test_blender.py` loads `studio.exr` from `C:\Users\Public\Documents\BlenderAutomationOutputs\studio.exr` for environment lighting. This file is **not in the repository** — it must be provided externally. If missing, Blender still renders but without environment reflections (the world shader node setup will fail silently). `test_blender2.py` does not require this file (it omits HDRI entirely).
- **GPU rendering:** `test_blender.py` forces `scene.cycles.device = 'GPU'`. If no compatible GPU is available, Blender will fall back to CPU silently.
- Claude Code permissions are configured in `.claude/settings.local.json`.
- The `.gitignore` excludes: `*.blend1`, `output_*.blend`, `*_frame_*.png`, `payload_dynamic_*.json`, `__pycache__/`, `server.pid`, `curlinsever.txt`, `test_output.blend`, `.b64`/`.tar.gz` deployment artifacts, `.tmp.driveupload/`, and `.claude/`.
- `.tmp.drivedownload/` and `Muapi/` are **not** yet in `.gitignore` — consider adding them (Google Drive sync temp dir and marketing data scratch dir, respectively).
- The Director-Server is an "island strategy" project — its Webpack config explicitly blocks resolution from the parent monorepo and forces all dependencies from its local `node_modules/`.

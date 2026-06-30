# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Blender automation pipeline that receives JSON payloads over HTTP and renders them as 3D `.blend` scene files. An external system (n8n, MCP client, etc.) POSTs campaign/product data to port 5000, and Blender generates dynamic geometry with camera animation headlessly.

## Architecture

```
POST /api/render  →  listen_blender.py (HTTP server, port 5000)
                    ├─ Saves payload → payload_{id}.json
                    ├─ Queues job in sequential worker thread
                    └─ Spawns: blender.exe --background --python test_blender.py -- payload_{id}.json
                                  └─ Reads JSON, builds 3D scenes, saves output_{id}.blend
```

- **`listen_blender.py`** — HTTP server + sequential job queue. Accepts POST at `/api/render`, immediately returns 200 to the client, then hands work off to a single background worker thread that runs Blender subprocesses one at a time. This prevents concurrent Blender instances from colliding.
- **`test_blender.py`** — The active Blender Python script. Clears the default scene, builds dynamic geometry from JSON data, creates materials, sets up a camera with keyframed animation, and saves the result.
- **`test_blender2.py`** — Earlier/alternative Blender script. Uses a different JSON schema (`content`, `mesh_type`, `id`). Unlike `test_blender.py`, this script expects **pre-existing named objects** in a `.blend` file (e.g. an `EndingRemarks` text object) — it modifies an existing scene rather than building one from scratch. Renders animation directly (`bpy.ops.render.render(animation=True)`) rather than saving a `.blend`.

## Key conventions

- Payload files: `payload_{cleanId}.json` → Output files: `output_{cleanId}.blend`
- Session IDs are sanitized to `[a-zA-Z0-9_-]` before use in filenames. If sanitization yields an empty string, the fallback is `"campaign_asset"`.
- The `.blend1` files are Blender's automatic backup files (generated on save).
- Blender executable path is **hardcoded** in `listen_blender.py`: `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`. Upgrading Blender requires updating this path.

## Dynamic geometry rules (in `test_blender.py`)

Geometry shape is chosen by keyword matching against `scene.description`:
- **"salt" or "crystal"** → icosphere (radius 1.0, subdivisions 2)
- **"rose" or "petal"** → torus (major_radius 0.8, minor_radius 0.2), uses `bpy.ops.mesh.primitive_torus_add` (not bmesh — `bmesh.ops.create_torus` was removed in Blender 5.1)
- **Default** → cube (size 1.5)

Each scene object is offset along the X-axis by `(scene_index - 1) * 4.0` units. Materials alternate between the first two colors from `tailwind_css_theme.color_scheme`: odd-indexed scenes get the primary color (roughness 0.15, metallic 0.4), even-indexed scenes get the secondary color (roughness 0.6, metallic 0.0).

Camera animation: starts at X=0.0 on frame 1, ends at X=`(scene_count - 1) * 4.0` on frame `scene_count * 30`, with linear interpolation.

## JSON payload schema

`test_blender.py` reads these fields, **all of which are optional** — the script falls back to sensible defaults when any field is missing:

| Field | Default if missing | Purpose |
|---|---|---|
| `shopify_handle` | `"default_product"` | Product identifier (used for logging only, not file naming) |
| `tailwind_css_theme.color_scheme` | `["#FFFFFF"]` | Array of hex colors; index 0 = odd scenes, index 1 = even scenes |
| `video_timeline` | `[]` (treated as 3 empty scenes) | Array of scene objects, each optionally with `description` to drive shape selection |

If `video_timeline` is empty or missing, 3 default cube scenes are generated.

Many production payloads use a **simpler blog-post schema** with fields like `title`, `content`, `sessionId`, `id`, and `shopify_handle` — without `tailwind_css_theme` or `video_timeline`. The script handles both shapes gracefully via its fallback defaults.

## Running the server

```
python listen_blender.py
```

Listens on `0.0.0.0:5000`. The server is stateless — restarting it clears the in-memory job queue but does not affect saved payload/output files on disk.

## Operational notes

- `curlinsever.txt` contains operational references including a bearer token, cloudflared tunnel setup, and Tailscale networking commands. This file is a scratchpad, not documentation.
- The server directory is `C:\Users\Public\Documents\BlenderAutomationOutputs`.
- Claude Code permissions are configured in `.claude/settings.local.json`.

## Testing

There is no automated test suite. Manual testing is done by POSTing JSON to `http://localhost:5000/api/render` and inspecting the generated `output_*.blend` file. The `payload.json` and `payload_dynamic.json` files in the root are minimal test payloads. The many `payload_*.json` files with descriptive names (e.g. `payload_eco-friendly-packaging.json`) are production payloads that map to their corresponding `output_*.blend` files.

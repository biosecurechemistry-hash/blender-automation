#!/usr/bin/env python3
r"""
Blender MCP Bridge — stdio JSON-RPC server exposing Blender + Open-Generative-AI tools.

Blender tools:
  run_pipeline    – POST a JSON payload to listen_blender.py (port 5000)
                    or spawn Blender headless directly if the server is down.
  modify_scene    – Inject arbitrary Python into a headless Blender instance
                    to mutate materials, cameras, objects, etc.
  get_scene_info  – Open a .blend headless and list objects, materials, cameras.

Open-Generative-AI tools:
  generate_image  – Generate PNG images via sd-cli.exe (Stable Diffusion).
  generate_video  – Generate videos via sd-cli.exe vid_gen mode.
  list_assets     – Scan blob_storage and render frame outputs.
  studio_status   – Health check for OGA app, models, and Blender pipeline.

Integration tools:
  vlc_control     – Control VLC playback via Lua HTTP interface.
  remote_services – Health check for kaliko services (WebUI, Ghostfolio, DB).

Usage (registered as an MCP server):
  claude mcp add blender --transport stdio -- \
      "C:\Program Files\Blender Foundation\Blender 5.1\5.1\python\bin\python.exe" \
      "C:\Users\Public\Documents\BlenderAutomationOutputs\blender_mcp_bridge.py"
"""

import sys
import json
import os
import subprocess
import tempfile
import time
import http.client
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BLENDER_EXE = os.environ.get(
    "BLENDER_EXE",
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
)
BLENDER_PORT = int(os.environ.get("BLENDER_PORT", "5000"))
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Open-Generative-AI desktop app paths
OGA_DIR = os.path.join(os.environ.get("APPDATA", ""), "open-generative-ai")
OGA_BIN_DIR = os.path.join(OGA_DIR, "local-ai", "bin")
OGA_MODELS_DIR = os.path.join(OGA_DIR, "local-ai", "models")
OGA_BLOB_DIR = os.path.join(OGA_DIR, "blob_storage")
SD_CLI_EXE = os.path.join(OGA_BIN_DIR, "sd-cli.exe")
SD_SERVER_EXE = os.path.join(OGA_BIN_DIR, "sd-server.exe")
QWEN_MODEL = os.path.join(OGA_MODELS_DIR, "Qwen3-4B-Instruct-2507-UD-Q4_K_XL.gguf")
SD_MODEL = os.path.join(OGA_MODELS_DIR, "ae.safetensors")

# ---------------------------------------------------------------------------
# Campaign subfolder routing
# ---------------------------------------------------------------------------
def campaign_output_path(campaign_id: str | None, subfolder: str,
                          fallback_root: str | None = None) -> str:
    """Resolve a subfolder path inside a campaign directory.

    If campaign_id is provided, assets land in::

        {OUTPUT_DIR}/campaign_{campaign_id}/{subfolder}/

    Otherwise they go to *fallback_root* (the flat root OUTPUT_DIR) so
    existing callers without a campaign_id continue to work.

    The returned directory is created if it doesn't already exist.
    """
    root = fallback_root or OUTPUT_DIR
    if campaign_id:
        dest = os.path.join(OUTPUT_DIR, f"campaign_{campaign_id}", subfolder)
    else:
        dest = root  # backward-compatible flat output
    os.makedirs(dest, exist_ok=True)
    return dest


# ---------------------------------------------------------------------------
# MCP stdio transport helpers
# ---------------------------------------------------------------------------
def send_jsonrpc(data: dict):
    """Write a JSON-RPC message to stdout (with Content-Length header)."""
    body = json.dumps(data, ensure_ascii=False)
    header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
    sys.stdout.write(header + body)
    sys.stdout.flush()


def recv_jsonrpc() -> dict | None:
    """Read a single JSON-RPC message from stdin."""
    # Read headers until empty line
    content_length = None
    while True:
        line = sys.stdin.readline()
        if not line:
            return None  # EOF
        line = line.strip()
        if line == "":
            break
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
    if content_length is None:
        return None
    body = sys.stdin.read(content_length)
    return json.loads(body)


# ---------------------------------------------------------------------------
# Tool: run_pipeline
# ---------------------------------------------------------------------------
def run_pipeline(payload_json: str) -> dict:
    """Send a JSON payload through the Blender pipeline.

    Tries the HTTP server (listen_blender.py on port 5000) first.
    Falls back to spawning Blender headless directly.
    """
    # Validate JSON
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON payload: {e}"}

    # Strategy 1: POST to the running HTTP server
    try:
        body = json.dumps(payload).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", BLENDER_PORT, timeout=5)
        conn.request("POST", "/api/render", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        result = json.loads(resp.read().decode())
        conn.close()
        return {"success": True, "method": "http_server", "result": result}
    except (ConnectionRefusedError, OSError, http.client.HTTPException):
        pass  # Fall through to direct Blender invocation

    # Strategy 2: Spawn Blender directly
    campaign_title = payload.get("campaign_title", "mcp_direct")
    payload_path = os.path.join(OUTPUT_DIR, f"payload_mcp_direct_{int(time.time()*1000)}.json")

    try:
        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        cmd = [BLENDER_EXE, "--background", "--python",
               os.path.join(OUTPUT_DIR, "test_blender.py"), "--", payload_path]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        # Extract the output .blend path from stdout
        blend_match = re.search(r"Saved master layout to: (.+\.blend)", proc.stdout)
        output_blend = blend_match.group(1) if blend_match else None

        # Count rendered frames
        frame_count = len(re.findall(r"Saved: '.+_frame_\d+\.png'", proc.stdout))

        return {
            "success": proc.returncode == 0,
            "method": "blender_direct",
            "returncode": proc.returncode,
            "output_blend": output_blend,
            "frames_rendered": frame_count,
            "campaign_title": campaign_title,
            "stderr_tail": "\n".join(proc.stderr.strip().split("\n")[-10:]),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Blender timed out after 300s"}
    except FileNotFoundError:
        return {"success": False, "error": f"Blender not found at: {BLENDER_EXE}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: modify_scene
# ---------------------------------------------------------------------------
def modify_scene(blend_file: str, python_code: str) -> dict:
    """Open a .blend headless, execute Python code inside Blender, save.

    Args:
        blend_file: Absolute path to the .blend file to modify.
        python_code: Blender Python code to execute (has access to bpy, bmesh, etc.).
    """
    if not os.path.isabs(blend_file):
        blend_file = os.path.join(OUTPUT_DIR, blend_file)
    if not os.path.exists(blend_file):
        return {"success": False, "error": f"Blend file not found: {blend_file}"}

    # Write the user's Python into a temp script
    script = f"""
import bpy
import json

# --- User code begins ---
{python_code}
# --- User code ends ---

# Save the modified scene
bpy.ops.wm.save_as_mainfile(filepath={json.dumps(blend_file)})
print("[MCP] Scene saved after modification.")
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                     delete=False, encoding="utf-8") as f:
        f.write(script)
        tmp_script = f.name

    try:
        cmd = [BLENDER_EXE, "--background", blend_file, "--python", tmp_script]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": "\n".join(proc.stdout.strip().split("\n")[-30:]),
            "stderr_tail": "\n".join(proc.stderr.strip().split("\n")[-10:]),
            "blend_file": blend_file,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Blender timed out after 120s"}
    except FileNotFoundError:
        return {"success": False, "error": f"Blender not found at: {BLENDER_EXE}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            os.unlink(tmp_script)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Tool: get_scene_info
# ---------------------------------------------------------------------------
def get_scene_info(blend_file: str) -> dict:
    """Open a .blend headless and dump scene metadata.

    Returns counts and names of objects, meshes, materials, cameras, lights,
    plus the active camera and render settings.
    """
    if not os.path.isabs(blend_file):
        blend_file = os.path.join(OUTPUT_DIR, blend_file)
    if not os.path.exists(blend_file):
        return {"success": False, "error": f"Blend file not found: {blend_file}"}

    inspector_script = f"""
import bpy
import json

info = {{}}

# All objects
info["object_count"] = len(bpy.data.objects)
info["objects"] = []
for obj in bpy.data.objects:
    info["objects"].append({{
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "hidden": obj.hide_viewport,
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
    }})

# Meshes
info["mesh_count"] = len(bpy.data.meshes)
info["meshes"] = [m.name for m in bpy.data.meshes]

# Materials
info["material_count"] = len(bpy.data.materials)
info["materials"] = []
for mat in bpy.data.materials:
    info["materials"].append({{
        "name": mat.name,
        "use_nodes": mat.use_nodes,
        "has_bsdf": "Principled BSDF" in mat.node_tree.nodes.keys()
                    if mat.use_nodes and mat.node_tree else False,
    }})

# Cameras
info["camera_count"] = len(bpy.data.cameras)
info["cameras"] = []
for cam in bpy.data.cameras:
    info["cameras"].append({{
        "name": cam.name,
        "lens": cam.lens,
        "dof_aperture": cam.dof.aperture_fstop if cam.dof else None,
        "dof_enabled": cam.dof.use_dof if cam.dof else False,
    }})

# Lights
info["light_count"] = len(bpy.data.lights)
info["lights"] = []
for light in bpy.data.lights:
    info["lights"].append({{
        "name": light.name,
        "type": light.type,
        "energy": light.energy,
        "color": list(light.color),
    }})

# Active camera
scene = bpy.context.scene
info["active_camera"] = scene.camera.name if scene.camera else None

# Render settings
info["render"] = {{
    "resolution_x": scene.render.resolution_x,
    "resolution_y": scene.render.resolution_y,
    "resolution_percentage": scene.render.resolution_percentage,
    "fps": scene.render.fps,
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "file_format": scene.render.image_settings.file_format,
    "engine": scene.render.engine,
}}

print("\\n[MCP_SCENE_INFO]")
print(json.dumps(info, indent=2, default=str))
print("[MCP_SCENE_INFO_END]")
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                     delete=False, encoding="utf-8") as f:
        f.write(inspector_script)
        tmp_script = f.name

    try:
        cmd = [BLENDER_EXE, "--background", blend_file, "--python", tmp_script]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        # Extract the JSON block between markers
        match = re.search(
            r"\[MCP_SCENE_INFO\]\n(.*?)\n\[MCP_SCENE_INFO_END\]",
            proc.stdout, re.DOTALL,
        )
        if match:
            scene_info = json.loads(match.group(1))
            return {"success": True, "blend_file": blend_file, "scene": scene_info}
        else:
            return {
                "success": False,
                "error": "Could not parse scene info from Blender output",
                "stdout_tail": "\n".join(proc.stdout.strip().split("\n")[-20:]),
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Blender timed out after 60s"}
    except FileNotFoundError:
        return {"success": False, "error": f"Blender not found at: {BLENDER_EXE}"}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON parse error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            os.unlink(tmp_script)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Tool: generate_image  (Open-Generative-AI — Stable Diffusion)
# ---------------------------------------------------------------------------
def generate_image(prompt: str, output_path: str = "", steps: int = 20,
                   width: int = 512, height: int = 512,
                   campaign_id: str = "") -> dict:
    """Generate an image via the local Stable Diffusion CLI (sd-cli.exe).

    Uses the Qwen 3 4B Instruct GGUF model as the text encoder and the
    bundled ae.safetensors autoencoder for decoding.

    When *campaign_id* is provided, the image is saved into
    ``campaign_<id>/_images/`` instead of the flat OUTPUT_DIR root.
    """
    if not os.path.exists(SD_CLI_EXE):
        return {"success": False,
                "error": f"sd-cli.exe not found at {SD_CLI_EXE}"}

    if not os.path.exists(SD_MODEL):
        return {"success": False,
                "error": f"SD model not found at {SD_MODEL}"}

    if not output_path:
        slug = re.sub(r"[^a-z0-9]+", "_", prompt.lower().strip())[:40]
        dest_dir = campaign_output_path(campaign_id if campaign_id else None,
                                         "_images")
        output_path = os.path.join(dest_dir, f"sd_{slug}_{int(time.time())}.png")

    cmd = [
        SD_CLI_EXE,
        "-M", "img_gen",
        "-m", SD_MODEL,
        "-o", output_path,
        "-p", prompt,
        "--steps", str(steps),
        "-W", str(width),
        "-H", str(height),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "output_path": output_path if os.path.exists(output_path) else None,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "steps": steps,
            "stdout_tail": "\n".join(proc.stdout.strip().split("\n")[-20:]),
            "stderr_tail": "\n".join(proc.stderr.strip().split("\n")[-10:]),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "SD image generation timed out after 300s"}
    except FileNotFoundError:
        return {"success": False, "error": f"sd-cli.exe not executable: {SD_CLI_EXE}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: list_assets  (Open-Generative-AI + Blender outputs)
# ---------------------------------------------------------------------------
def list_assets(source: str = "all") -> dict:
    """List generated media assets across local stores.

    Args:
        source: "blob" (OGA blob_storage only), "renders" (Blender frames only),
                "all" (both, default).
    """
    result = {"success": True, "assets": {}}

    # Open-Generative-AI blob storage
    if source in ("all", "blob"):
        blob_assets = []
        if os.path.isdir(OGA_BLOB_DIR):
            for root, dirs, files in os.walk(OGA_BLOB_DIR):
                for f in files:
                    fpath = os.path.join(root, f)
                    try:
                        st = os.stat(fpath)
                        blob_assets.append({
                            "name": f,
                            "path": fpath,
                            "size_bytes": st.st_size,
                            "modified": time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(st.st_mtime)),
                        })
                    except OSError:
                        pass
        result["assets"]["blob_storage"] = {
            "path": OGA_BLOB_DIR,
            "count": len(blob_assets),
            "files": blob_assets[:50],  # Cap at 50 to avoid flooding
        }

    # Blender render frame outputs — scan campaign subfolders first,
    # then fall back to flat root for legacy assets.
    if source in ("all", "renders"):
        render_assets = []
        scan_roots = []

        # 1. Structured campaign folders (new)
        if os.path.isdir(OUTPUT_DIR):
            for entry in sorted(os.listdir(OUTPUT_DIR)):
                campaign_frames = os.path.join(OUTPUT_DIR, entry, "frames")
                if entry.startswith("campaign_") and os.path.isdir(campaign_frames):
                    scan_roots.append(campaign_frames)

        # 2. Flat root (legacy / fallback)
        scan_roots.append(OUTPUT_DIR)

        for scan_root in scan_roots:
            if not os.path.isdir(scan_root):
                continue
            for f in sorted(os.listdir(scan_root)):
                if re.search(r"_frame_\d+\.png$", f):
                    fpath = os.path.join(scan_root, f)
                    try:
                        st = os.stat(fpath)
                        render_assets.append({
                            "name": f,
                            "path": fpath,
                            "size_bytes": st.st_size,
                            "modified": time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.localtime(st.st_mtime)),
                        })
                    except OSError:
                        pass

        # Group by campaign prefix
        campaigns = {}
        for a in render_assets:
            prefix = re.sub(r"_frame_\d+\.png$", "", a["name"])
            campaigns.setdefault(prefix, []).append(a)
        result["assets"]["renders"] = {
            "path": OUTPUT_DIR,
            "total_frames": len(render_assets),
            "campaigns": {k: len(v) for k, v in campaigns.items()},
            "latest_10": render_assets[-10:],
        }

    return result


# ---------------------------------------------------------------------------
# Tool: studio_status  (Open-Generative-AI health check)
# ---------------------------------------------------------------------------
def studio_status() -> dict:
    """Check the status of the Open-Generative-AI desktop app and its components."""
    status = {
        "app_directory": OGA_DIR,
        "app_exists": os.path.isdir(OGA_DIR),
        "components": {},
    }

    # Stable Diffusion CLI
    status["components"]["sd_cli"] = {
        "path": SD_CLI_EXE,
        "installed": os.path.exists(SD_CLI_EXE),
        "size_bytes": os.path.getsize(SD_CLI_EXE) if os.path.exists(SD_CLI_EXE) else 0,
    }

    # SD Server
    status["components"]["sd_server"] = {
        "path": SD_SERVER_EXE,
        "installed": os.path.exists(SD_SERVER_EXE),
    }

    # Models
    status["components"]["models"] = {}
    if os.path.isdir(OGA_MODELS_DIR):
        for f in os.listdir(OGA_MODELS_DIR):
            fpath = os.path.join(OGA_MODELS_DIR, f)
            if os.path.isfile(fpath):
                size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 1)
                status["components"]["models"][f] = f"{size_mb} MB"

    # Blob storage
    blob_count = 0
    blob_size = 0
    if os.path.isdir(OGA_BLOB_DIR):
        for root, dirs, files in os.walk(OGA_BLOB_DIR):
            for f in files:
                try:
                    st = os.stat(os.path.join(root, f))
                    blob_count += 1
                    blob_size += st.st_size
                except OSError:
                    pass
    status["components"]["blob_storage"] = {
        "path": OGA_BLOB_DIR,
        "files": blob_count,
        "total_size_mb": round(blob_size / (1024 * 1024), 1),
    }

    # Blender renders — scan campaign subfolders first, then flat root
    frame_count = 0
    blend_count = 0
    campaign_count = 0
    if os.path.isdir(OUTPUT_DIR):
        # Structured campaign folders
        for entry in os.listdir(OUTPUT_DIR):
            entry_path = os.path.join(OUTPUT_DIR, entry)
            if entry.startswith("campaign_") and os.path.isdir(entry_path):
                campaign_count += 1
                for root, dirs, files in os.walk(entry_path):
                    for f in files:
                        if re.search(r"_frame_\d+\.png$", f):
                            frame_count += 1
                        elif f.endswith(".blend"):
                            blend_count += 1
        # Legacy flat root files (backward compatible)
        for f in os.listdir(OUTPUT_DIR):
            fpath = os.path.join(OUTPUT_DIR, f)
            if not os.path.isfile(fpath):
                continue
            if re.search(r"_frame_\d+\.png$", f):
                frame_count += 1
            elif f.endswith(".blend"):
                blend_count += 1
    status["components"]["blender_outputs"] = {
        "path": OUTPUT_DIR,
        "campaigns": campaign_count,
        "render_frames": frame_count,
        "blend_files": blend_count,
    }

    status["components"]["listen_blender"] = {
        "port": BLENDER_PORT,
        "running": False,
    }
    try:
        conn = http.client.HTTPConnection("127.0.0.1", BLENDER_PORT, timeout=2)
        conn.request("GET", "/")
        conn.getresponse()
        status["components"]["listen_blender"]["running"] = True
        conn.close()
    except Exception:
        pass

    return {"success": True, "status": status}


# ---------------------------------------------------------------------------
# Tool: generate_video  (Open-Generative-AI — Video Studio)
# ---------------------------------------------------------------------------
def generate_video(prompt: str, frames: int = 24, fps: int = 24,
                   width: int = 512, height: int = 512,
                   output_path: str = "", seed: int = 42,
                   campaign_id: str = "") -> dict:
    """Generate a video via sd-cli.exe vid_gen mode using the local Stable
    Diffusion engine. Outputs .avi, .webm, or animated .webp.

    When *campaign_id* is provided, the video is saved into
    ``campaign_<id>/_video/`` instead of the flat OUTPUT_DIR root.
    """
    if not os.path.exists(SD_CLI_EXE):
        return {"success": False,
                "error": f"sd-cli.exe not found at {SD_CLI_EXE}"}
    if not os.path.exists(SD_MODEL):
        return {"success": False,
                "error": f"SD model not found at {SD_MODEL}"}

    if not output_path:
        slug = re.sub(r"[^a-z0-9]+", "_", prompt.lower().strip())[:30]
        dest_dir = campaign_output_path(campaign_id if campaign_id else None,
                                         "_video")
        output_path = os.path.join(
            dest_dir, f"vid_{slug}_{int(time.time())}.webm")

    cmd = [
        SD_CLI_EXE,
        "-M", "vid_gen",
        "-m", SD_MODEL,
        "-o", output_path,
        "-p", prompt,
        "--video-frames", str(frames),
        "--fps", str(fps),
        "-H", str(height),
        "-W", str(width),
        "-s", str(seed),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "output_path": output_path if os.path.exists(output_path) else None,
            "prompt": prompt,
            "frames": frames,
            "fps": fps,
            "size": f"{width}x{height}",
            "stdout_tail": "\n".join(proc.stdout.strip().split("\n")[-20:]),
            "stderr_tail": "\n".join(proc.stderr.strip().split("\n")[-10:]),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Video generation timed out after 600s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: vlc_control  (VLC Lua HTTP interface)
# ---------------------------------------------------------------------------
VLC_HOST = os.environ.get("VLC_HOST", "localhost")
VLC_PORT = int(os.environ.get("VLC_PORT", "8080"))
VLC_PASS = os.environ.get("VLC_PASS", "")


def vlc_control(action: str, file_path: str = "", volume: int = -1) -> dict:
    """Control VLC media player via its Lua HTTP interface.

    Args:
        action: One of 'status', 'play', 'pause', 'stop', 'next', 'prev',
                'fullscreen', 'play_file', 'seek', 'loop'.
        file_path: When action='play_file', the absolute path to media to play.
                   Supports passing a directory of PNG frames for frame-by-frame review.
        volume: Volume 0-512 (only applied when action='play_file' or 'volume').
    """
    import urllib.request
    import urllib.parse

    vlc_base = f"http://{VLC_HOST}:{VLC_PORT}/requests"

    try:
        if action == "status":
            url = f"{vlc_base}/status.json"
            req = urllib.request.Request(url)
            if VLC_PASS:
                req.add_header("Authorization",
                               "Basic " + __import__("base64").b64encode(
                                   f":{VLC_PASS}".encode()).decode())
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            return {"success": True, "action": "status", "vlc": data}

        elif action == "play_file" and file_path:
            # Add to playlist and play
            encoded = urllib.parse.quote(file_path, safe="")
            url = (f"{vlc_base}/status.json"
                   f"?command=in_enqueue&input={encoded}")
            req = urllib.request.Request(url)
            if VLC_PASS:
                req.add_header("Authorization",
                               "Basic " + __import__("base64").b64encode(
                                   f":{VLC_PASS}".encode()).decode())
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            # Set volume if specified
            if volume >= 0:
                url = (f"{vlc_base}/status.json"
                       f"?command=volume&val={min(volume, 512)}")
                req = urllib.request.Request(url)
                if VLC_PASS:
                    req.add_header("Authorization",
                                   "Basic " + __import__("base64").b64encode(
                                       f":{VLC_PASS}".encode()).decode())
                urllib.request.urlopen(req, timeout=5)

            return {"success": True, "action": "play_file",
                    "file": file_path, "vlc": data}

        elif action in ("play", "pause", "stop", "next", "prev", "fullscreen",
                        "loop"):
            cmd_map = {"pause": "pl_pause", "next": "pl_next",
                       "prev": "pl_previous", "fullscreen": "fullscreen",
                       "loop": "pl_loop"}
            cmd = cmd_map.get(action, action)
            url = f"{vlc_base}/status.json?command={cmd}"
            req = urllib.request.Request(url)
            if VLC_PASS:
                req.add_header("Authorization",
                               "Basic " + __import__("base64").b64encode(
                                   f":{VLC_PASS}".encode()).decode())
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            return {"success": True, "action": action, "vlc": data}

        elif action == "seek":
            # Seek to position in seconds
            sec = int(file_path) if file_path else 0
            url = f"{vlc_base}/status.json?command=seek&val={sec}"
            req = urllib.request.Request(url)
            if VLC_PASS:
                req.add_header("Authorization",
                               "Basic " + __import__("base64").b64encode(
                                   f":{VLC_PASS}".encode()).decode())
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            return {"success": True, "action": "seek", "seconds": sec,
                    "vlc": data}

        elif action == "volume" and volume >= 0:
            url = (f"{vlc_base}/status.json"
                   f"?command=volume&val={min(volume, 512)}")
            req = urllib.request.Request(url)
            if VLC_PASS:
                req.add_header("Authorization",
                               "Basic " + __import__("base64").b64encode(
                                   f":{VLC_PASS}".encode()).decode())
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            return {"success": True, "action": "volume", "volume": volume,
                    "vlc": data}

        else:
            return {"success": False,
                    "error": f"Unknown action '{action}' or missing file_path"}

    except urllib.error.URLError as e:
        return {"success": False,
                "error": (f"VLC not reachable at {vlc_base}. "
                          f"Is the HTTP interface enabled? {e}")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: remote_services  (health check for kaliko-hosted services)
# ---------------------------------------------------------------------------
KALIKO_HOST = os.environ.get("KALIKO_HOST", "100.104.14.63")


def remote_services() -> dict:
    """Health check for all remote services on kaliko (Tailscale).

    Checks: Open WebUI (3335), Ghostfolio (3334), Postgres (5433),
    shopify-publish (3002), blender-api (3006), director-mcp (8000).
    """
    checks = {}
    endpoints = {
        "open_webui": (3335, "/"),
        "ghostfolio": (3334, "/"),
        "shopify_publish": (3002, "/api/publish_auto"),
        "blender_api": (3006, "/"),
        "director_mcp": (8000, "/"),
    }

    for name, (port, path) in endpoints.items():
        try:
            conn = http.client.HTTPConnection(KALIKO_HOST, port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            checks[name] = {
                "host": f"{KALIKO_HOST}:{port}",
                "reachable": True,
                "http_status": resp.status,
            }
            conn.close()
        except Exception as e:
            checks[name] = {
                "host": f"{KALIKO_HOST}:{port}",
                "reachable": False,
                "error": str(e),
            }

    # Postgres
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((KALIKO_HOST, 5433))
        sock.close()
        checks["postgres"] = {
            "host": f"{KALIKO_HOST}:5433",
            "reachable": result == 0,
        }
    except Exception as e:
        checks["postgres"] = {
            "host": f"{KALIKO_HOST}:5433",
            "reachable": False,
            "error": str(e),
        }

    # Tailscale status
    online_count = sum(1 for c in checks.values() if c.get("reachable"))
    checks["summary"] = {
        "total": len(checks),
        "online": online_count,
        "offline": len(checks) - online_count,
    }

    return {"success": True, "services": checks}

TOOLS = [
    {
        "name": "run_pipeline",
        "description": (
            "Run the Blender automation pipeline with a JSON payload. "
            "Posts to listen_blender.py on port 5000, or spawns Blender "
            "headless directly if the server is not running. "
            "Payload schema: {campaign_title: str, prompt_brief: str}. "
            "Returns the output .blend path and frame count."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payload_json": {
                    "type": "string",
                    "description": "JSON string of the pipeline payload.",
                },
            },
            "required": ["payload_json"],
        },
    },
    {
        "name": "modify_scene",
        "description": (
            "Open a .blend file headless and execute arbitrary Blender Python "
            "code to modify the scene (materials, camera, objects, lighting, "
            "etc.), then save. The code has full access to bpy, bmesh, math, "
            "and mathutils. Example: change camera f-stop with "
            "bpy.data.cameras['Cinematic_Micro_Cam'].dof.aperture_fstop = 0.8"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "blend_file": {
                    "type": "string",
                    "description": "Absolute path to the .blend file to modify.",
                },
                "python_code": {
                    "type": "string",
                    "description": (
                        "Blender Python code to execute. Full bpy access. "
                        "The scene is saved automatically after execution."
                    ),
                },
            },
            "required": ["blend_file", "python_code"],
        },
    },
    {
        "name": "get_scene_info",
        "description": (
            "Open a .blend file headless and inspect its contents. "
            "Returns all objects (name, type, location, parent/child hierarchy), "
            "meshes, materials (with node info), cameras (lens, DOF settings), "
            "lights (type, energy, color), the active camera, and render settings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "blend_file": {
                    "type": "string",
                    "description": "Absolute path to the .blend file to inspect.",
                },
            },
            "required": ["blend_file"],
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Generate an image via the local Stable Diffusion engine bundled "
            "with the Open-Generative-AI desktop app (sd-cli.exe). "
            "Uses ae.safetensors autoencoder for decoding. "
            "Output is saved to the BlenderAutomationOutputs directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text prompt describing the image to generate.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional absolute path for the output PNG. Auto-generated if omitted.",
                },
                "steps": {
                    "type": "integer",
                    "description": "Denoising steps (default: 20). More = higher quality, slower.",
                },
                "width": {
                    "type": "integer",
                    "description": "Image width in pixels (default: 512).",
                },
                "height": {
                    "type": "integer",
                    "description": "Image height in pixels (default: 512).",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Optional campaign ID (e.g. '52580'). When set, the image is routed into campaign_<id>/_images/ instead of the root output directory.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "list_assets",
        "description": (
            "List generated media assets across local stores: "
            "Open-Generative-AI blob_storage and Blender render frame outputs. "
            "Groups render frames by campaign prefix."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Which asset store to scan: 'blob', 'renders', or 'all' (default).",
                },
            },
        },
    },
    {
        "name": "studio_status",
        "description": (
            "Health check for the Open-Generative-AI desktop app and Blender pipeline. "
            "Reports installed models, SD binaries, blob storage usage, render frame "
            "counts, and whether listen_blender.py is running."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "generate_video",
        "description": (
            "Generate a video via the local Stable Diffusion engine bundled "
            "with Open-Generative-AI (sd-cli.exe vid_gen mode). "
            "Outputs .webm, .avi, or animated .webp to the render directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text prompt describing the video to generate.",
                },
                "frames": {
                    "type": "integer",
                    "description": "Number of video frames to generate (default: 24).",
                },
                "fps": {
                    "type": "integer",
                    "description": "Frames per second (default: 24).",
                },
                "width": {
                    "type": "integer",
                    "description": "Frame width in pixels (default: 512).",
                },
                "height": {
                    "type": "integer",
                    "description": "Frame height in pixels (default: 512).",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional output path. Auto-generated if omitted.",
                },
                "seed": {
                    "type": "integer",
                    "description": "RNG seed (default: 42, random if < 0).",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "Optional campaign ID (e.g. '52580'). When set, the video is routed into campaign_<id>/_video/ instead of the root output directory.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "vlc_control",
        "description": (
            "Control VLC media player via its Lua HTTP interface. "
            "Actions: status, play, pause, stop, next, prev, fullscreen, "
            "play_file (with file_path to a video or frame directory), "
            "seek (file_path=seconds), volume (volume=0-512), loop. "
            "Use play_file with a frame PNG directory to review renders frame-by-frame."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Control action: status, play, pause, stop, next, prev, fullscreen, play_file, seek, volume, loop.",
                },
                "file_path": {
                    "type": "string",
                    "description": "For play_file: absolute path to media. For seek: seconds as string.",
                },
                "volume": {
                    "type": "integer",
                    "description": "Volume level 0-512 (for play_file and volume actions).",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "remote_services",
        "description": (
            "Health check for all remote services on kaliko via Tailscale: "
            "Open WebUI (3335), Ghostfolio (3334), shopify-publish (3002), "
            "blender-api (3006), director-mcp (8000), and Postgres (5433). "
            "Returns reachability and HTTP status for each."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_request(msg: dict):
    """Dispatch a single JSON-RPC request/notification."""
    msg_id = msg.get("id")
    method = msg.get("method", "")

    if method == "initialize":
        send_jsonrpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "blender-mcp-bridge",
                    "version": "1.0.0",
                },
            },
        })

    elif method == "notifications/initialized":
        pass  # No response needed for notifications

    elif method == "tools/list":
        send_jsonrpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOLS},
        })

    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "run_pipeline":
            result = run_pipeline(arguments.get("payload_json", "{}"))
        elif tool_name == "modify_scene":
            result = modify_scene(
                arguments.get("blend_file", ""),
                arguments.get("python_code", ""),
            )
        elif tool_name == "get_scene_info":
            result = get_scene_info(arguments.get("blend_file", ""))
        elif tool_name == "generate_image":
            result = generate_image(
                arguments.get("prompt", ""),
                arguments.get("output_path", ""),
                int(arguments.get("steps", 20)),
                int(arguments.get("width", 512)),
                int(arguments.get("height", 512)),
                arguments.get("campaign_id", ""),
            )
        elif tool_name == "list_assets":
            result = list_assets(arguments.get("source", "all"))
        elif tool_name == "studio_status":
            result = studio_status()
        elif tool_name == "generate_video":
            result = generate_video(
                arguments.get("prompt", ""),
                int(arguments.get("frames", 24)),
                int(arguments.get("fps", 24)),
                int(arguments.get("width", 512)),
                int(arguments.get("height", 512)),
                arguments.get("output_path", ""),
                int(arguments.get("seed", 42)),
                arguments.get("campaign_id", ""),
            )
        elif tool_name == "vlc_control":
            result = vlc_control(
                arguments.get("action", "status"),
                arguments.get("file_path", ""),
                int(arguments.get("volume", -1)),
            )
        elif tool_name == "remote_services":
            result = remote_services()
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        # MCP requires tools/call to return content blocks
        text = json.dumps(result, indent=2, ensure_ascii=False)
        send_jsonrpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": text}],
            },
        })

    elif method == "ping":
        send_jsonrpc({"jsonrpc": "2.0", "id": msg_id, "result": {}})

    else:
        send_jsonrpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })


def main():
    """Main stdio loop."""
    # Log startup info to stderr (stdout is the MCP transport)
    print(f"[blender_mcp_bridge] PID={os.getpid()}  BLENDER_EXE={BLENDER_EXE}",
          file=sys.stderr, flush=True)

    while True:
        try:
            msg = recv_jsonrpc()
            if msg is None:
                break  # EOF — parent closed stdin
            handle_request(msg)
        except json.JSONDecodeError as e:
            print(f"[blender_mcp_bridge] JSON decode error: {e}",
                  file=sys.stderr, flush=True)
        except BrokenPipeError:
            break
        except Exception as e:
            print(f"[blender_mcp_bridge] Unhandled error: {e}",
                  file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()

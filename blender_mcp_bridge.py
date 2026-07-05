#!/usr/bin/env python3
r"""
Blender MCP Bridge — stdio JSON-RPC server exposing Blender automation tools.

Tools:
  run_pipeline    – POST a JSON payload to listen_blender.py (port 5000)
                    or spawn Blender headless directly if the server is down.
  modify_scene    – Inject arbitrary Python into a headless Blender instance
                    to mutate materials, cameras, objects, etc.
  get_scene_info  – Open a .blend headless and list objects, materials, cameras.

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
# MCP server loop
# ---------------------------------------------------------------------------
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

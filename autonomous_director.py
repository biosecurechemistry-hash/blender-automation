#!/usr/bin/env python3
r"""
Autonomous Director — full-cycle orchestrator for the Blender pipeline.

Receives payloads on port 42617, sanitizes them, forwards to the Blender
render queue, then (in a background thread) polls for frame output
completion, verifies via VLC, and stages the result on Shopify.

Architecture:
  POST /  (port 42617)
    ├─ Sanitize payload
    ├─ Forward to listen_blender.py (port 5000) → returns immediately
    └─ Background hook:
         ├─ Poll output dir for {campaign_title}_frame_*.png
         ├─ VLC verify: play first frame, check directory
         └─ Shopify: POST to /api/publish_auto with status=hidden
"""

import os
import sys
import json
import time
import re
import glob
import threading
import urllib.request
import urllib.parse
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TARGET_BLENDER_PORT = int(os.environ.get("BLENDER_PORT", "5000"))
LISTENER_PORT = int(os.environ.get("DIRECTOR_PORT", "42617"))
OUTPUT_DIR = os.environ.get(
    "RENDER_OUTPUT_DIR",
    r"C:\Users\Public\Documents\BlenderAutomationOutputs",
)
SHOPIFY_PUBLISH_URL = os.environ.get(
    "SHOPIFY_PUBLISH_URL",
    "http://100.104.14.63:3002/api/publish_auto",
)
VLC_HOST = os.environ.get("VLC_HOST", "localhost")
VLC_PORT = int(os.environ.get("VLC_PORT", "8080"))
VLC_PASS = os.environ.get("VLC_PASS", "")
POLL_INTERVAL = float(os.environ.get("DIRECTOR_POLL_INTERVAL", "5.0"))
POLL_TIMEOUT = float(os.environ.get("DIRECTOR_POLL_TIMEOUT", "900.0"))


# ---------------------------------------------------------------------------
# VLC helpers (mirrors blender_mcp_bridge.vlc_control)
# ---------------------------------------------------------------------------
def _vlc_request(endpoint: str) -> dict | None:
    """Send a GET to the VLC HTTP interface, return parsed JSON or None."""
    vlc_base = f"http://{VLC_HOST}:{VLC_PORT}/requests"
    url = f"{vlc_base}/{endpoint}"
    req = urllib.request.Request(url)
    if VLC_PASS:
        req.add_header(
            "Authorization",
            "Basic " + base64.b64encode(f":{VLC_PASS}".encode()).decode(),
        )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def vlc_status() -> dict:
    """Return VLC playback status."""
    data = _vlc_request("status.json")
    if data is None:
        return {"reachable": False, "error": "no response"}
    if "error" in data:
        return {"reachable": False, "error": data["error"]}
    return {"reachable": True, "state": data.get("state", "unknown"),
            "position": data.get("position", 0),
            "length": data.get("length", 0),
            "volume": data.get("volume", 0)}


def vlc_play_file(file_path: str) -> dict:
    """Enqueue and play a file (or directory of frames) in VLC."""
    encoded = urllib.parse.quote(file_path, safe="")
    data = _vlc_request(f"status.json?command=in_enqueue&input={encoded}")
    if data is None:
        return {"success": False, "error": "no response"}
    return {"success": True, "file": file_path, "vlc": data}


def vlc_pause() -> dict:
    data = _vlc_request("status.json?command=pl_pause")
    return {"success": data is not None and "error" not in (data or {})}


# ---------------------------------------------------------------------------
# Frame verification
# ---------------------------------------------------------------------------
def count_rendered_frames(campaign_title: str) -> int:
    """Count how many {campaign_title}_frame_*.png files exist."""
    pattern = os.path.join(OUTPUT_DIR, f"{campaign_title}_frame_*.png")
    return len(glob.glob(pattern))


def verify_frame_directory(campaign_title: str,
                           expected_frames: int) -> dict:
    """Check that the expected number of frames exist and are non-empty."""
    pattern = os.path.join(OUTPUT_DIR, f"{campaign_title}_frame_*.png")
    files = sorted(glob.glob(pattern))
    actual = len(files)
    sizes = []
    for f in files:
        try:
            sizes.append(os.path.getsize(f))
        except OSError:
            sizes.append(0)
    zero_byte = sum(1 for s in sizes if s == 0)
    return {
        "campaign_title": campaign_title,
        "expected_frames": expected_frames,
        "actual_frames": actual,
        "complete": actual >= expected_frames,
        "total_size_bytes": sum(sizes),
        "zero_byte_files": zero_byte,
        "first_frame": files[0] if files else None,
        "last_frame": files[-1] if files else None,
    }


# ---------------------------------------------------------------------------
# Shopify staging
# ---------------------------------------------------------------------------
def stage_shopify(payload: dict) -> dict:
    """POST a hidden product to the Shopify publish buffer."""
    import http.client

    # Build a minimal staging payload from the director payload
    campaign_title = payload.get("campaign_title", "untitled")
    prompt_brief = payload.get("prompt_brief", "")
    product_type = payload.get("product_type", "Blog Post")
    vendor = payload.get("vendor", "Hotel Organic")
    tags = payload.get("tags", [])

    shopify_body = {
        "status": "hidden",
        "title": campaign_title.replace("_", " "),
        "body_html": f"<p>{prompt_brief}</p>",
        "product_type": product_type,
        "vendor": vendor,
        "tags": tags,
    }

    try:
        body = json.dumps(shopify_body).encode("utf-8")
        # Parse host:port from the URL
        url = SHOPIFY_PUBLISH_URL
        if url.startswith("http://"):
            url = url[7:]
        elif url.startswith("https://"):
            url = url[8:]
        host, _, port_str = url.partition(":")
        host = host.rstrip("/")
        port = int(port_str.split("/")[0]) if port_str else 80
        path = "/" + url.partition("/")[2] if "/" in url else "/"

        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        result = json.loads(resp.read().decode())
        conn.close()
        return {"success": True, "shopify_response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Post-render hook (runs in background thread)
# ---------------------------------------------------------------------------
def post_render_hook(payload: dict, queue_id: str):
    """Background hook: wait for render, verify, stage to Shopify."""
    campaign_title = payload.get("campaign_title", "Dynamic_Asset")
    frame_start = payload.get("frame_start", 1)
    frame_end = payload.get("frame_end", 120)
    expected_frames = frame_end - frame_start + 1

    print(f"\n[HOOK:{queue_id}] Post-render hook started for "
          f"'{campaign_title}' (expecting {expected_frames} frames)")

    # --- Phase 1: Poll for render completion ---
    start_time = time.time()
    last_count = 0
    while True:
        elapsed = time.time() - start_time
        current_count = count_rendered_frames(campaign_title)

        if current_count != last_count:
            print(f"[HOOK:{queue_id}] Frames: {current_count}/{expected_frames}  "
                  f"({elapsed:.0f}s elapsed)")
            last_count = current_count

        if current_count >= expected_frames:
            print(f"[HOOK:{queue_id}] All {expected_frames} frames rendered "
                  f"in {elapsed:.0f}s")
            break

        if elapsed > POLL_TIMEOUT:
            print(f"[HOOK:{queue_id}] TIMEOUT after {POLL_TIMEOUT}s — "
                  f"only {current_count}/{expected_frames} frames rendered")
            return  # Abort — don't stage incomplete renders

        time.sleep(POLL_INTERVAL)

    # --- Phase 2: Verify frame integrity ---
    verify = verify_frame_directory(campaign_title, expected_frames)
    print(f"[HOOK:{queue_id}] Frame verify: {verify['actual_frames']} files, "
          f"{verify['total_size_bytes']} bytes total, "
          f"{verify['zero_byte_files']} zero-byte")

    if verify["zero_byte_files"] > 0:
        print(f"[HOOK:{queue_id}] WARNING: {verify['zero_byte_files']} "
              f"zero-byte files detected — possible render corruption")

    # --- Phase 3: VLC verification ---
    vlc = vlc_status()
    print(f"[HOOK:{queue_id}] VLC status: {vlc}")

    if vlc.get("reachable"):
        # Play the first rendered frame as a quick visual verification
        first_frame = verify.get("first_frame")
        if first_frame:
            play_result = vlc_play_file(first_frame)
            print(f"[HOOK:{queue_id}] VLC play first frame: "
                  f"{'OK' if play_result.get('success') else 'FAILED'}")

        # Also enqueue the full frame sequence directory for review
        frame_dir = os.path.join(OUTPUT_DIR, "")
        vlc_play_file(frame_dir)
        # Pause immediately — the user can press play to review
        time.sleep(1)
        vlc_pause()
        print(f"[HOOK:{queue_id}] VLC: frame directory queued and paused "
              f"for manual review")
    else:
        print(f"[HOOK:{queue_id}] VLC not reachable — skipping playback "
              f"verification")

    # --- Phase 4: Stage to Shopify ---
    print(f"[HOOK:{queue_id}] Staging to Shopify...")
    shopify_result = stage_shopify(payload)
    if shopify_result.get("success"):
        print(f"[HOOK:{queue_id}] Shopify: BUFFERED — "
              f"{shopify_result['shopify_response'].get('status', '?')}")
    else:
        print(f"[HOOK:{queue_id}] Shopify: FAILED — "
              f"{shopify_result.get('error', 'unknown')}")

    print(f"[HOOK:{queue_id}] Post-render hook complete for "
          f"'{campaign_title}'")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class AutonomousOrchestrator(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "empty body"}).encode())
            return

        raw_data = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_data.decode('utf-8'))

            # 1. Sanitize
            sanitized_timeline = []
            if "video_timeline" in payload:
                for scene in payload["video_timeline"]:
                    if "description" in scene:
                        scene["description"] = str(
                            scene["description"]).lstrip('=')
                    sanitized_timeline.append(scene)
                payload["video_timeline"] = sanitized_timeline

            if "sessionId" not in payload or not payload["sessionId"]:
                payload["sessionId"] = payload.get(
                    "id", "autonomous_organic_generation")

            campaign_title = payload.get("campaign_title", "untitled")
            print(f"\n[DIRECTOR] Received payload for '{campaign_title}'")

            # 2. Forward to Blender queue
            response = requests.post(
                f"http://127.0.0.1:{TARGET_BLENDER_PORT}/api/render",
                json=payload, timeout=5)
            blender_resp = response.json()
            queue_id = blender_resp.get("id", "unknown")

            # 3. Spawn post-render hook in background
            hook_thread = threading.Thread(
                target=post_render_hook,
                args=(payload, queue_id),
                daemon=True,
                name=f"hook-{queue_id}",
            )
            hook_thread.start()
            print(f"[DIRECTOR] Queued '{campaign_title}' as {queue_id} "
                  f"— post-render hook started")

            # 4. Return immediately
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "queued",
                "id": queue_id,
                "campaign_title": campaign_title,
                "hook_active": True,
                "blender_response": blender_resp,
            }).encode('utf-8'))

        except json.JSONDecodeError as e:
            print(f"[DIRECTOR] Invalid JSON: {e}")
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "invalid JSON"}).encode())
        except Exception as e:
            print(f"[DIRECTOR] CRITICAL: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        """Suppress default HTTP request logging — we log explicitly."""
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run():
    print(f"[*] Director Bridge Active on port {LISTENER_PORT}")
    print(f"[*] Blender target: 127.0.0.1:{TARGET_BLENDER_PORT}")
    print(f"[*] Output dir:     {OUTPUT_DIR}")
    print(f"[*] Shopify target: {SHOPIFY_PUBLISH_URL}")
    print(f"[*] VLC target:     {VLC_HOST}:{VLC_PORT}")
    print(f"[*] Poll timeout:   {POLL_TIMEOUT}s  interval: {POLL_INTERVAL}s")
    server = HTTPServer(('0.0.0.0', LISTENER_PORT), AutonomousOrchestrator)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Director shutting down.")


if __name__ == '__main__':
    import requests  # keep at top-level for clarity
    run()

#!/usr/bin/env python3
r"""
Blender Automation Bridge — Kali Linux Island Edition.

HTTP listener on port 5000.  Accepts JSON payloads, saves them to
RENDER_OUTPUT_DIR, and spawns Blender headless in a sequential queue.

Payload schema (all fields optional):
  {
    "campaign_title":    "my_product",       // default: "Dynamic_Asset"
    "prompt_brief":      "SEO description",  // default: ""
    "geometry":          "helix|grid|sphere|ring",
    "material":          "chrome|matte|glass|emissive|gold",
    "lighting":          "studio|warm|dramatic|soft",
    "frame_start":       1,
    "frame_end":         120,
    "resolution_x":      1920,
    "resolution_y":      1080,
    ...  (see test_blender.py for full schema)
  }

Usage:
  python3 listen_blender.py
  BLENDER_EXE=/opt/blender/blender python3 listen_blender.py

Environment:
  BLENDER_EXE      — path to Blender executable (default: /usr/local/bin/blender)
  BLENDER_PORT     — TCP port to listen on (default: 5000)
  RENDER_OUTPUT_DIR — where frames and .blend files land
  MOLECULAR_SCRIPT  — path to the Blender Python scene generator
"""

import http.server
import socketserver
import json
import subprocess
import os
import re
import sys
import threading
import queue
import time
import atexit
import signal


# ---------------------------------------------------------------------------
# Configuration (env vars with sensible defaults)
# ---------------------------------------------------------------------------
BLENDER_EXE = os.environ.get("BLENDER_EXE", "/usr/local/bin/blender")
PORT = int(os.environ.get("BLENDER_PORT", "5000"))
OUTPUT_DIR = os.environ.get(
    "RENDER_OUTPUT_DIR",
    os.path.expanduser("~/Director-Server/outputs"),
)
MOLECULAR_SCRIPT = os.environ.get(
    "MOLECULAR_SCRIPT",
    os.path.expanduser("~/Director-Server/molecular_sweep.py"),
)
PID_FILE = os.path.join(OUTPUT_DIR, "server.pid")

# Ensure output directory exists.
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# PID file — prevents duplicate server instances
# ---------------------------------------------------------------------------
def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running (Linux)."""
    try:
        os.kill(pid, 0)  # Signal 0 tests existence
        return True
    except (OSError, ProcessLookupError):
        return False


def cleanup_pid_file():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


if os.path.exists(PID_FILE):
    try:
        with open(PID_FILE, 'r') as f:
            old_pid = int(f.read().strip())
        if is_process_running(old_pid):
            print(f"[!] Server already running (PID {old_pid}). "
                  f"Remove {PID_FILE} if stale.")
            sys.exit(1)
        print(f"[*] Removing stale PID file: {PID_FILE}")
        os.remove(PID_FILE)
    except (ValueError, OSError):
        print(f"[*] Removing corrupt PID file: {PID_FILE}")
        os.remove(PID_FILE)

with open(PID_FILE, 'w') as f:
    f.write(str(os.getpid()))
atexit.register(cleanup_pid_file)

# Also clean up on SIGTERM / SIGINT
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))


# ---------------------------------------------------------------------------
# Sequential job queue (single worker prevents Blender collisions)
# ---------------------------------------------------------------------------
job_queue = queue.Queue()


def blender_queue_worker():
    print("[*] Background Blender Queue Worker Engine Initialized.")
    while True:
        cmd, payload_filename = job_queue.get()
        print(f"\n[*] Queue Engine executing Blender worker for: "
              f"{payload_filename}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                print(f"[!] Blender exited with code {result.returncode}:")
                stderr_tail = "\n".join(
                    result.stderr.strip().split("\n")[-20:]
                )
                print(stderr_tail)
            else:
                print(f"[+] Queue Engine completed: {payload_filename}")
        except subprocess.TimeoutExpired:
            print(f"[!] Blender timed out after 300s: {payload_filename}")
        except FileNotFoundError:
            print(f"[!] Blender executable not found: '{BLENDER_EXE}'. "
                  f"Set BLENDER_EXE env var.")
        except Exception as e:
            print(f"[!] Worker error processing {payload_filename}: {e}")
        finally:
            job_queue.task_done()


# Spin up exactly ONE background thread to process renders sequentially.
threading.Thread(target=blender_queue_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class BlenderHandler(http.server.SimpleHTTPRequestHandler):
    def do_HEAD(self):
        """Lightweight health check — returns 200 if the server is alive."""
        if self.path == '/api/render' or self.path == '/health':
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "queue_depth": job_queue.qsize(),
                "blender_exe": BLENDER_EXE,
                "output_dir": OUTPUT_DIR,
            }).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != '/api/render':
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "empty body"}).encode())
            return

        post_data = self.rfile.read(content_length)

        try:
            decoded = post_data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
            payload = json.loads(decoded)

            # Derive a unique, filesystem-safe ID.
            raw_id = payload.get('sessionId', payload.get('campaign_title', 'dynamic'))
            clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(raw_id).split('/')[-1])
            if not clean_id or clean_id == '_':
                clean_id = "campaign_asset"

            timestamp = str(int(time.time() * 1000))
            unique_id = f"{clean_id}_{timestamp}"

            print(f"[+] Accepted and Queued payload ID: {unique_id}")

            payload_filename = os.path.join(
                OUTPUT_DIR, f"payload_{unique_id}.json",
            )
            with open(payload_filename, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            cmd = [
                BLENDER_EXE,
                "--background",
                "--python", MOLECULAR_SCRIPT,
                "--",
                payload_filename,
            ]

            # --- STEP 1: IMMEDIATELY RELEASE NETWORK SOCKET ---
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "queued",
                "id": unique_id,
            }).encode('utf-8'))

            # --- STEP 2: HAND OFF TO SEQUENTIAL QUEUE ---
            job_queue.put((cmd, payload_filename))

        except json.JSONDecodeError as e:
            print(f"[!] Invalid JSON in request: {e}")
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "invalid JSON"}).encode())
        except Exception as e:
            print(f"[!] Server processing crash: {e}")
            self.send_response(500)
            self.end_headers()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    with ThreadedTCPServer(("0.0.0.0", PORT), BlenderHandler) as httpd:
        print(f"[*] Blender Bridge Active on http://0.0.0.0:{PORT}")
        print(f"[*] Blender:  {BLENDER_EXE}")
        print(f"[*] Script:   {MOLECULAR_SCRIPT}")
        print(f"[*] Outputs:  {OUTPUT_DIR}")
        print(f"[*] PID:      {os.getpid()}  (file: {PID_FILE})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[!] Shutting down Blender Bridge.")

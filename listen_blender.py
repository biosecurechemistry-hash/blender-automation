#!/usr/bin/env python3
"""Blender automation HTTP bridge — receives JSON payloads on port 5000,
queues them, and spawns Blender headlessly to generate .blend scene files.

Usage: python3 listen_blender.py
Environment: BLENDER_EXE  — path to Blender executable (default: "blender")
             BLENDER_PORT — TCP port to listen on (default: 5000)
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

# --- Configuration (env vars with sensible defaults) ---
BLENDER_EXE = os.environ.get("BLENDER_EXE", "blender")
PORT = int(os.environ.get("BLENDER_PORT", "5000"))
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.pid")

# --- PID file — prevents duplicate server instances ---
def is_process_running(pid):
    """Check if a process with the given PID is running (cross-platform)."""
    if sys.platform == 'win32':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)  # Signal 0 tests existence on Unix
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
            print(f"[!] Server already running (PID {old_pid}). Remove {PID_FILE} if stale.")
            sys.exit(1)
        # PID file is stale — the process is gone
        print(f"[*] Removing stale PID file: {PID_FILE}")
        os.remove(PID_FILE)
    except (ValueError, OSError):
        # Corrupt or unreadable PID file
        print(f"[*] Removing corrupt PID file: {PID_FILE}")
        os.remove(PID_FILE)

with open(PID_FILE, 'w') as f:
    f.write(str(os.getpid()))
atexit.register(cleanup_pid_file)

# --- Sequential job queue (single worker prevents Blender collisions) ---
job_queue = queue.Queue()

def blender_queue_worker():
    print("[*] Background Blender Queue Worker Engine Initialized.")
    while True:
        cmd, payload_filename = job_queue.get()
        print(f"\n[*] Queue Engine executing Blender worker for: {payload_filename}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                print(f"[!] Blender exited with code {result.returncode}:")
                # Print last 20 lines of stderr — usually contains the relevant traceback
                stderr_tail = "\n".join(result.stderr.strip().split("\n")[-20:])
                print(stderr_tail)
            else:
                print(f"[+] Queue Engine completed processing: {payload_filename}")
        except subprocess.TimeoutExpired:
            print(f"[!] Blender timed out after 300s processing: {payload_filename}")
        except FileNotFoundError:
            print(f"[!] Blender executable not found: '{BLENDER_EXE}'. Set BLENDER_EXE env var.")
        except Exception as e:
            print(f"[!] Queue Engine worker error processing {payload_filename}: {str(e)}")
        finally:
            job_queue.task_done()

# Spin up exactly ONE background thread to process renders sequentially
threading.Thread(target=blender_queue_worker, daemon=True).start()

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/render':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "empty body"}).encode('utf-8'))
                return

            post_data = self.rfile.read(content_length)

            try:
                decoded_data = post_data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
                payload = json.loads(decoded_data)

                raw_session_id = payload.get('sessionId', 'dynamic')
                clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_session_id.split('/')[-1])
                if not clean_id or clean_id == '_':
                    clean_id = "campaign_asset"

                # Append timestamp to prevent collisions when same sessionId
                # arrives twice before the first job is dequeued
                timestamp = str(int(time.time() * 1000))
                unique_id = f"{clean_id}_{timestamp}"

                print(f"[+] Accepted and Queued payload ID: {unique_id}")

                payload_filename = f"payload_{unique_id}.json"
                with open(payload_filename, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)

                cmd = [
                    BLENDER_EXE,
                    "--background",
                    "--python",
                    "test_blender.py",
                    "--",
                    payload_filename
                ]

                # --- STEP 1: IMMEDIATELY RELEASE NETWORK SOCKET ---
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "queued", "id": unique_id}).encode('utf-8'))

                # --- STEP 2: HAND OFF TO SEQUENTIAL QUEUE ---
                job_queue.put((cmd, payload_filename))

            except json.JSONDecodeError as e:
                print(f"[!] Invalid JSON in request: {str(e)}")
                try:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "invalid JSON"}).encode('utf-8'))
                except:
                    pass
            except Exception as e:
                print(f"[!] Server processing crash: {str(e)}")
                try:
                    self.send_response(500)
                    self.end_headers()
                except:
                    pass

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    with ThreadedTCPServer(("0.0.0.0", PORT), MyHandler) as httpd:
        print(f"[*] Robust Queued Blender Bridge Active on http://0.0.0.0:{PORT}...")
        print(f"[*] Blender executable: {BLENDER_EXE}")
        print(f"[*] PID: {os.getpid()}  (PID file: {PID_FILE})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[!] Shutting down server bridge.")

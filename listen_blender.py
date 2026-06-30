import http.server
import socketserver
import json
import subprocess
import os
import re
import threading
import queue

PORT = 5000

# Create an infinite thread-safe task queue
job_queue = queue.Queue()

def blender_queue_worker():
    print("[*] Background Blender Queue Worker Engine Initialized.")
    while True:
        # Pull the next job from the queue (blocks gracefully until an item arrives)
        cmd, payload_filename = job_queue.get()
        print(f"\n[*] Queue Engine executing Blender worker for: {payload_filename}")
        try:
            subprocess.run(cmd)
            print(f"[+] Queue Engine completed processing: {payload_filename}")
        except Exception as e:
            print(f"[!] Queue Engine worker error processing {payload_filename}: {str(e)}")
        finally:
            job_queue.task_done()

# Spin up exactly ONE background thread to process renders sequentially
threading.Thread(target=blender_queue_worker, daemon=True).start()

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/render':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                decoded_data = post_data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
                payload = json.loads(decoded_data)
                
                raw_session_id = payload.get('sessionId', 'dynamic')
                clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_session_id.split('/')[-1])
                if not clean_id or clean_id == '_':
                    clean_id = "campaign_asset"

                print(f"[+] Accepted and Queued payload ID: {clean_id}")

                payload_filename = f"payload_{clean_id}.json"
                with open(payload_filename, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)

                cmd = [
                    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe",
                    "--background",
                    "--python",
                    "test_blender.py",
                    "--",
                    payload_filename
                ]

                # --- STEP 1: IMMEDIATELY RELEASE NETWORK SOCKET (Prevents 502/10053) ---
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "queued", "id": clean_id}).encode('utf-8'))
                
                # --- STEP 2: HAND OFF TO SEQUENTIAL QUEUE ---
                job_queue.put((cmd, payload_filename))

            except Exception as e:
                print(f"[!] Server processing crash: {str(e)}")
                try:
                    self.send_response(500)
                    self.end_headers()
                except:
                    pass

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

with ThreadedTCPServer(("0.0.0.0", PORT), MyHandler) as httpd:
    print(f"[*] Robust Queued Blender Bridge Active on http://0.0.0.0:{PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down server bridge.")

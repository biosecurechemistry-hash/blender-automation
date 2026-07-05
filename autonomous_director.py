import os
import sys
import json
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

TARGET_BLENDER_PORT = 5000
LEDGER_DB_PORT = 5433
LISTENER_PORT = 42617

class AutonomousOrchestrator(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        raw_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(raw_data.decode('utf-8'))
            print("[INFO] Payload intercepted by Agent 42617. Starting auto-sanitization.")
            
            # 1. Structural Self-Healing: Strip syntax anomalies discovered by Allseer
            sanitized_timeline = []
            if "video_timeline" in payload:
                for scene in payload["video_timeline"]:
                    if "description" in scene:
                        scene["description"] = str(scene["description"]).lstrip('=')
                    sanitized_timeline.append(scene)
                payload["video_timeline"] = sanitized_timeline

            # 2. State Validation: Ensure session token alignment
            if "sessionId" not in payload or not payload["sessionId"]:
                payload["sessionId"] = payload.get("id", "autonomous_organic_generation")

            # 3. Hand off to the Blender background queue engine
            response = requests.post(f"http://127.0.0.1:{TARGET_BLENDER_PORT}/api/render", json=payload)
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "forwarded", "blender_response": response.json()}).encode('utf-8'))
            
        except Exception as e:
            print(f"[CRITICAL] Orchestration failure: {str(e)}")
            self.send_response(500)
            self.end_headers()

def run():
    print(f"[*] Autonomous Organic Entity Bridge Active on Port {LISTENER_PORT}...")
    server = HTTPServer(('0.0.0.0', LISTENER_PORT), AutonomousOrchestrator)
    server.serve_forever()

if __name__ == '__main__':
    run()

import os
import sys
import time
import subprocess

# Default watch directory
WATCH_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(r"~\Director-Server\assets\cells")
DIRECTOR_SCRIPT = "autonomous_director.py"

print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Watcher started. Monitoring: {WATCH_DIR}")

# Ensure target watch directory exists
os.makedirs(WATCH_DIR, exist_ok=True)

class SimpleFolderWatcher:
    def __init__(self, watch_dir):
        self.watch_dir = watch_dir
        self.before = dict([(f, os.path.getmtime(os.path.join(watch_dir, f))) for f in os.listdir(watch_dir) if os.path.isfile(os.path.join(watch_dir, f))])

    def check(self):
        after = dict([(f, os.path.getmtime(os.path.join(watch_dir, f))) for f in os.listdir(watch_dir) if os.path.isfile(os.path.join(watch_dir, f))])
        added = [f for f in after if not f in self.before]
        modified = [f for f in after if f in self.before and after[f] != self.before[f]]
        self.before = after
        return added, modified

if __name__ == "__main__":
    watcher = SimpleFolderWatcher(WATCH_DIR)
    while True:
        try:
            added, modified = watcher.check()
            if added or modified:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] New cell activity detected! Triggering autonomous_director...")
                # Invoke autonomous_director using the current interpreter
                subprocess.Popen([sys.executable, DIRECTOR_SCRIPT])
            time.sleep(2)
        except Exception as e:
            print(f"Watcher error: {e}", file=sys.stderr)
            time.sleep(2)
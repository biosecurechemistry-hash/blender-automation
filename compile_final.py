"""
Campaign 52580 — Final MP4 Compilation v2 (File-Based)
========================================================
Converts PNG frames → raw RGB24 temp file → ffmpeg H.264 + AAC.
Avoids pipe deadlock by staging the raw video to disk first.
"""

import subprocess
import os
import sys
import time
from PIL import Image

CAMPAIGN_DIR = r"C:\Users\Public\Documents\BlenderAutomationOutputs\campaign_52580"
FRAMES_DIR   = os.path.join(CAMPAIGN_DIR, "frames")
AUDIO_FILE   = os.path.join(CAMPAIGN_DIR, "_audio", "Anti_Ageing_Argan_Lavender_Voiceover.wav")
OUTPUT_MP4   = os.path.join(CAMPAIGN_DIR, "Anti_Ageing_Argan_Lavender_Final.mp4")
RAW_TEMP     = os.path.join(CAMPAIGN_DIR, "_cache", "_frames_raw.rgb")
FFMPEG       = r"C:\Program Files\BlueStacks_nxt\ffmpeg.exe"

FPS = 24
WIDTH = 960
HEIGHT = 540
FRAME_BYTES = WIDTH * HEIGHT * 3  # RGB24

# --- Load frames into memory ---
frame_files = sorted(
    f for f in os.listdir(FRAMES_DIR)
    if f.startswith("Anti_Ageing_Argan_Lavender_frame_") and f.endswith(".png")
)
if not frame_files:
    print("ERROR: No frames found.")
    sys.exit(1)

print(f"Loading {len(frame_files)} frames...")
frames_raw = []
for fname in frame_files:
    fpath = os.path.join(FRAMES_DIR, fname)
    img = Image.open(fpath).convert("RGB")
    frames_raw.append(img.tobytes())
    sys.stdout.write(f"\r  {len(frames_raw)}/{len(frame_files)}")
    sys.stdout.flush()
print()

# --- Write raw frames to temp file (looped to fill 48s) ---
total_duration = 48.0
total_frames = int(total_duration * FPS)
print(f"Writing {total_frames} raw frames ({total_duration}s @ {FPS}fps) to temp file...")

with open(RAW_TEMP, "wb") as f:
    for i in range(total_frames):
        f.write(frames_raw[i % len(frames_raw)])
        if i % 240 == 0 and i > 0:
            pct = i / total_frames * 100
            written_mb = (i * FRAME_BYTES) / (1024 * 1024)
            sys.stdout.write(f"\r  {i}/{total_frames} ({pct:.0f}%) — {written_mb:.0f} MB")
            sys.stdout.flush()

raw_size_mb = os.path.getsize(RAW_TEMP) / (1024 * 1024)
print(f"\r  Done: {raw_size_mb:.1f} MB raw data written\n")

# --- Compile with ffmpeg ---
cmd = [
    FFMPEG, "-y",
    "-f", "rawvideo",
    "-pixel_format", "rgb24",
    "-video_size", f"{WIDTH}x{HEIGHT}",
    "-framerate", str(FPS),
    "-i", RAW_TEMP,
    "-i", AUDIO_FILE,
    "-c:v", "libopenh264",
    "-b:v", "2M",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-shortest",
    "-movflags", "+faststart",
    OUTPUT_MP4,
]

print("Encoding with ffmpeg (libopenh264 + AAC)...")
start = time.time()
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
elapsed = time.time() - start

if result.returncode == 0 and os.path.exists(OUTPUT_MP4):
    size_kb = os.path.getsize(OUTPUT_MP4) / 1024
    print(f"SUCCESS — {size_kb:.1f} KB in {elapsed:.1f}s")
else:
    print(f"FAILED (exit {result.returncode})")
    for line in result.stderr.split("\n")[-10:]:
        if line.strip():
            print(f"  {line.strip()}")

# --- Cleanup temp ---
try:
    os.remove(RAW_TEMP)
    print("Cleaned up temp file.")
except:
    pass

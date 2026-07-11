r"""
Campaign 52580 — Final Video Compilation
========================================
Imports the 24-frame PNG image sequence + 48s voiceover WAV
into Blender's Video Sequence Editor and renders an MP4.

Usage (run from BlenderAutomationOutputs):
  "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python compile_video.py
"""

import bpy
import os
import glob

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CAMPAIGN_DIR = r"C:\Users\Public\Documents\BlenderAutomationOutputs\campaign_52580"
FRAMES_DIR   = os.path.join(CAMPAIGN_DIR, "frames")
AUDIO_DIR    = os.path.join(CAMPAIGN_DIR, "_audio")
OUTPUT_DIR   = os.path.join(CAMPAIGN_DIR, "_video")
FRAME_PREFIX = "Anti_Ageing_Argan_Lavender_frame_"
WAV_FILE     = os.path.join(AUDIO_DIR, "Anti_Ageing_Argan_Lavender_Voiceover.wav")
OUTPUT_MP4   = os.path.join(OUTPUT_DIR, "Anti_Ageing_Argan_Lavender_Final.mp4")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Gather frames
# ---------------------------------------------------------------------------
frame_files = sorted(glob.glob(os.path.join(FRAMES_DIR, f"{FRAME_PREFIX}*.png")))
if not frame_files:
    raise RuntimeError(f"No frames found in {FRAMES_DIR}")
first_frame = frame_files[0]
frame_count = len(frame_files)
print(f"[COMPILE] Found {frame_count} frames")

# ---------------------------------------------------------------------------
# Wipe any leftover scene data
# ---------------------------------------------------------------------------
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end   = frame_count

# Clear existing strips (Blender 5.1 API: 'strips' not 'sequences')
if bpy.context.scene.sequence_editor:
    for strip in list(bpy.context.scene.sequence_editor.strips_all):
        bpy.context.scene.sequence_editor.strips.remove(strip)

# Ensure we have a sequence editor
if not bpy.context.scene.sequence_editor:
    bpy.context.scene.sequence_editor_create()

seq_editor = bpy.context.scene.sequence_editor

# ---------------------------------------------------------------------------
# Strip 1: Image sequence (Video)
# ---------------------------------------------------------------------------
print(f"[COMPILE] Adding image sequence: {first_frame}")
img_strip = seq_editor.strips.new_image(
    name="Campaign52580_Frames",
    filepath=first_frame,
    channel=1,
    frame_start=1,
)
# Set frame final duration to match the audio length
# Image strip defaults to 1 frame — stretch to full frame count
img_strip.frame_final_duration = frame_count
# Use BLEND interpolation for smooth cross-fades between frames
img_strip.use_proxy = False
img_strip.blend_type = 'REPLACE'
print(f"[COMPILE] Image strip: frames 1-{frame_count}, duration={img_strip.frame_final_duration}")

# ---------------------------------------------------------------------------
# Strip 2: Audio
# ---------------------------------------------------------------------------
if os.path.exists(WAV_FILE):
    print(f"[COMPILE] Adding audio: {os.path.basename(WAV_FILE)}")
    audio_strip = seq_editor.strips.new_sound(
        name="Voiceover",
        filepath=WAV_FILE,
        channel=2,
        frame_start=1,
    )
    # Set audio volume to full
    audio_strip.volume = 1.0
    print(f"[COMPILE] Audio strip: duration={audio_strip.frame_final_duration} frames "
          f"({audio_strip.frame_final_duration / bpy.context.scene.render.fps:.1f}s)")
else:
    print(f"[COMPILE] WARNING: Audio file not found: {WAV_FILE}")

# ---------------------------------------------------------------------------
# Adjust scene to match audio length
# ---------------------------------------------------------------------------
# Stretch image sequence to match audio duration if needed
audio_frames = audio_strip.frame_final_duration if os.path.exists(WAV_FILE) else frame_count
scene = bpy.context.scene

# Set the render range to cover both video and audio
scene.frame_start = 1
scene.frame_end = max(frame_count, int(audio_frames))
# Loop or extend the image sequence to match audio length
img_strip.frame_final_duration = scene.frame_end

print(f"[COMPILE] Scene frames: {scene.frame_start}-{scene.frame_end}")

# ---------------------------------------------------------------------------
# Render settings — H.264 MP4 via FFmpeg
# ---------------------------------------------------------------------------
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
scene.render.ffmpeg.ffmpeg_preset = 'GOOD'
scene.render.ffmpeg.audio_codec = 'AAC'
scene.render.ffmpeg.audio_bitrate = 192
scene.render.ffmpeg.audio_volume = 1.0
scene.render.ffmpeg.gopsize = 18
scene.render.ffmpeg.use_autosplit = True

# Video output settings
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100
scene.render.fps = 24

# Output path
scene.render.filepath = os.path.splitext(OUTPUT_MP4)[0] + "_"  # Blender appends frame range
# Actually, for a single file output, we don't want frame numbering.
# Use a workaround: render to a temp directory then rename.
scene.render.use_file_extension = True
scene.render.use_overwrite = True
scene.render.use_sequencer = True

# For single-file MP4 output without frame numbering:
# Blender will append frame range if %d isn't in the filename.
# Setting frame_start == frame_end forces single frame, but we want a video.
# Use the ffmpeg output approach instead.
scene.render.filepath = os.path.join(OUTPUT_DIR, "Anti_Ageing_Argan_Lavender_Final")

print(f"[COMPILE] Output: {scene.render.filepath}.mp4")
print(f"[COMPILE] Resolution: {scene.render.resolution_x}x{scene.render.resolution_y}")
print(f"[COMPILE] FPS: {scene.render.fps}")
print(f"[COMPILE] Codec: H.264 + AAC @ 192kbps")

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
print(f"\n[COMPILE] Rendering {scene.frame_end - scene.frame_start + 1} frames with audio...")
bpy.ops.render.render(animation=True)

# The output may have a frame number suffix — find and rename
import glob as g
actual_files = sorted(g.glob(os.path.join(OUTPUT_DIR, "Anti_Ageing_Argan_Lavender_Final*")))
if actual_files:
    final = actual_files[-1]
    if final != OUTPUT_MP4:
        # Remove old if exists
        if os.path.exists(OUTPUT_MP4):
            os.remove(OUTPUT_MP4)
        os.rename(final, OUTPUT_MP4)
        print(f"[COMPILE] Renamed: {os.path.basename(final)} → {os.path.basename(OUTPUT_MP4)}")

# Verify
if os.path.exists(OUTPUT_MP4):
    size_kb = os.path.getsize(OUTPUT_MP4) / 1024
    print(f"\n[SUCCESS] Final video: {OUTPUT_MP4}")
    print(f"[SUCCESS] Size: {size_kb:.1f} KB")
else:
    # Check if Blender added a frame suffix
    alt = os.path.join(OUTPUT_DIR, "Anti_Ageing_Argan_Lavender_Final0001.mp4")
    if os.path.exists(alt):
        os.rename(alt, OUTPUT_MP4)
        size_kb = os.path.getsize(OUTPUT_MP4) / 1024
        print(f"\n[SUCCESS] Final video: {OUTPUT_MP4}")
        print(f"[SUCCESS] Size: {size_kb:.1f} KB")
    else:
        # List what was actually output
        all_files = os.listdir(OUTPUT_DIR)
        print(f"\n[COMPILE] Files in output dir: {all_files}")
        # Search for any mp4
        mp4s = [f for f in all_files if f.endswith('.mp4')]
        if mp4s:
            actual = os.path.join(OUTPUT_DIR, mp4s[0])
            if actual != OUTPUT_MP4:
                os.rename(actual, OUTPUT_MP4)
            print(f"[SUCCESS] Final video: {OUTPUT_MP4}")
            print(f"[SUCCESS] Size: {os.path.getsize(OUTPUT_MP4)/1024:.1f} KB")

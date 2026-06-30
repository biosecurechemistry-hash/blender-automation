#!/usr/bin/env python3
"""Blender scene generator — reads a JSON payload and builds dynamic 3D geometry.

Called by listen_blender.py:
    blender.exe --background --python test_blender.py -- payload_{id}.json

Produces: output_{id}.blend
"""

import bpy
import bmesh
import json
import sys
import os


# --- Blender version guard ---
MAJOR, MINOR = bpy.app.version[:2]
if (MAJOR, MINOR) < (5, 1):
    print(f"[!] Blender {MAJOR}.{MINOR} is too old — need 5.1+")
    sys.exit(1)


def clear_workspace():
    """Purges placeholder meshes, materials, and generic defaults."""
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def build_dynamic_geometry(data):
    """Interprets rich campaign JSON parameters to construct dynamic scenes."""
    handle = data.get("shopify_handle", "default_product")
    colors = data.get("tailwind_css_theme", {}).get("color_scheme", ["#FFFFFF"])
    scenes = data.get("video_timeline", [])
    scene_count = len(scenes) if scenes else 3

    print(f"[*] Core Processor Active for: {handle}")
    print(f"[*] Generating {scene_count} scene meshes based on timeline index...")

    def hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip('#')
        return tuple(int(hex_str[i:i+2], 16)/255.0 for i in (0, 2, 4)) + (1.0,)

    primary_color = hex_to_rgb(colors[0]) if len(colors) > 0 else (0.8, 0.5, 0.5, 1.0)
    secondary_color = hex_to_rgb(colors[1]) if len(colors) > 1 else (0.2, 0.2, 0.2, 1.0)

    for idx, scene_data in enumerate(scenes, start=1):
        x_offset = (idx - 1) * 4.0
        description = scene_data.get("description", "").lower()

        # --- PARSING RULE: Check text keywords to change shapes dynamically ---
        if "rose" in description or "petal" in description:
            # bmesh.ops.create_torus was removed in Blender 5.1
            # Use object-level torus primitive instead
            bpy.ops.mesh.primitive_torus_add(
                major_radius=0.8, minor_radius=0.2,
                align='WORLD', location=(x_offset, 0, 0)
            )
            obj = bpy.context.object
            obj.name = f"Asset_Scene_{idx}"
            obj.data.name = f"Mesh_Scene_{idx}"
        else:
            mesh = bpy.data.meshes.new(f"Mesh_Scene_{idx}")
            obj = bpy.data.objects.new(f"Asset_Scene_{idx}", mesh)
            bpy.context.collection.objects.link(obj)

            bm = bmesh.new()
            if "salt" in description or "crystal" in description:
                # Generate a crystalline icosphere shape for salt
                bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
            else:
                # Fallback to standard tracking block cube
                bmesh.ops.create_cube(bm, size=1.5)

            # Apply the layout offset spacing along the X-axis
            for v in bm.verts:
                v.co.x += x_offset

            bm.to_mesh(mesh)
            bm.free()

        mat = bpy.data.materials.new(name=f"Mat_Scene_{idx}")
        # use_nodes is True by default in Blender 5.1+ (removed in 6.0)
        nodes = mat.node_tree.nodes
        principled = nodes.get("Principled BSDF")

        if principled:
            principled.inputs['Base Color'].default_value = primary_color if idx % 2 != 0 else secondary_color
            principled.inputs['Roughness'].default_value = 0.15 if idx % 2 != 0 else 0.6
            principled.inputs['Metallic'].default_value = 0.4 if idx % 2 != 0 else 0.0

        obj.data.materials.append(mat)

    return scene_count


def add_automated_camera(scene_count):
    """Spawns an automated camera that smoothly glides along the X-axis tracking the scenes."""
    print(f"[*] Automating Cinematic Camera Rig for {scene_count} scenes...")

    cam_data = bpy.data.cameras.new("Cinematic_Camera")
    cam_obj = bpy.data.objects.new("Camera_Player", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    bpy.context.scene.camera = cam_obj
    cam_obj.location = (0.0, -7.0, 1.2)
    cam_obj.rotation_euler = (1.4, 0.0, 0.0)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = scene_count * 30

    scene.frame_set(1)
    cam_obj.location.x = 0.0
    cam_obj.keyframe_insert(data_path="location", index=0)

    final_frame = scene.frame_end
    scene.frame_set(final_frame)
    cam_obj.location.x = (scene_count - 1) * 4.0
    cam_obj.keyframe_insert(data_path="location", index=0)

    if cam_obj.animation_data and cam_obj.animation_data.action:
        curves = getattr(cam_obj.animation_data.action, "curves",
                         getattr(cam_obj.animation_data.action, "fcurves", []))
        for fcurve in curves:
            for kp in fcurve.keyframe_points:
                kp.interpolation = 'LINEAR'


def derive_output_path(payload_path):
    """Convert a payload filename to its corresponding output path.

    Uses os.path to be platform-agnostic. Replaces 'payload_' prefix
    in the basename with 'output_' and switches extension to .blend.
    """
    dir_name = os.path.dirname(payload_path)
    base_name = os.path.basename(payload_path)

    if base_name.startswith("payload_"):
        base_name = "output_" + base_name[len("payload_"):]
    else:
        base_name = "output_" + base_name

    if base_name.endswith(".json"):
        base_name = base_name[:-len(".json")] + ".blend"

    return os.path.join(dir_name, base_name) if dir_name else base_name


# --- PIPELINE INITIALIZATION GATE ---
if __name__ == "__main__":
    # Pull the targeted payload file path passed by listen_blender.py
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

    if not args:
        print("[!] Execution halted: No target payload configuration argument detected.")
        sys.exit(1)

    payload_path = args[0]
    print(f"[*] Blender {MAJOR}.{MINOR} — processing: {payload_path}")

    with open(payload_path, 'r', encoding='utf-8') as f:
        campaign_data = json.load(f)

    clear_workspace()
    total_scenes = build_dynamic_geometry(campaign_data)
    add_automated_camera(total_scenes)

    output_path = derive_output_path(payload_path)
    bpy.ops.wm.save_as_mainfile(filepath=output_path)
    print(f"[+] Production Pipeline complete! File saved as: {output_path}")
